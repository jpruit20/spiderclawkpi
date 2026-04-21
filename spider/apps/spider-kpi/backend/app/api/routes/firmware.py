"""Firmware Hub — device drill-down, live shadow, session history, and
program overview (beta/alpha/gamma).

Phase 1 is view-only. All actual firmware *deploy* endpoints (OTA push,
cohort assignment, alpha promotion) will land in a later phase and will
be owner-gated the same way the ECR tracker is.

Device identity convention:

  * **MAC** — 12-hex-char lowercase (``fcb467f9b456``). Accepted in any
    format (colons, dashes, mixed case — ``normalize_mac`` collapses).
  * **``TelemetryStreamEvent.device_id``** — a 32-char DynamoDB hash,
    NOT the MAC. The MAC lives at
    ``raw_payload->device_data->reported->mac``. One physical grill can
    map to multiple ``device_id`` values (different user accounts pair
    with the same grill → distinct hashes). Lookup resolves MAC to the
    full set of associated ``device_id`` values and reads sessions
    across all of them.

The JSON path is backed by an expression index
(``ix_telemetry_stream_events_reported_mac`` — migration 0036).

Live shadow freshness is ~15 s (AWS poll cadence). The UI polls the
shadow endpoint on that cadence while a device view is open.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import Integer, case, desc, func, select, text
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.api.routes.auth import get_user_from_request
from app.models import (
    AppSideDeviceObservation,
    BetaCohortMember,
    FirmwareDeviceRecent,
    FirmwareRelease,
    TelemetrySession,
    TelemetryStreamEvent,
)
from app.services import cook_state_classifier as cook_state
from app.services.cook_behavior_baselines import get_baseline_lookup


logger = logging.getLogger(__name__)

ACTIVE_COOK_WINDOW_SECONDS = 120
SHADOW_TRAIL_SAMPLES = 60
DEFAULT_SESSION_LIMIT = 20
# Cap the device_id resolution — if the frontend asks about a MAC that
# has been paired across hundreds of accounts, we still only hit the top
# N most-recent device_ids when pulling session history.
MAX_DEVICE_IDS_PER_MAC = 25

router = APIRouter(prefix="/api/firmware", tags=["firmware"])


# ---------------------------------------------------------------------------
# Tiny TTL cache for the firmware /overview/metrics aggregate queries.
# Scoped to this module; one entry per (start, end, firmware_version)
# tuple. 90 s TTL is tight enough that the 30 s poll Command Center
# does elsewhere still sees fresh numbers within a couple poll cycles,
# and loose enough to absorb page-reload bursts that otherwise re-run
# the same ~11 s aggregate.
# ---------------------------------------------------------------------------

_METRICS_CACHE_TTL_SECONDS = 90
_metrics_cache: dict[tuple[str, str, str | None], tuple[float, list]] = {}


def _metrics_cache_key(start_dt: datetime, end_dt: datetime, firmware_version: str | None) -> tuple[str, str, str | None]:
    # Round to the minute so many clients in the same poll window share
    # a cache slot rather than each computing a slightly-different slice.
    return (
        start_dt.replace(second=0, microsecond=0).isoformat(),
        end_dt.replace(second=0, microsecond=0).isoformat(),
        firmware_version,
    )


def _metrics_cache_get(start_dt: datetime, end_dt: datetime, firmware_version: str | None) -> list | None:
    import time as _time
    key = _metrics_cache_key(start_dt, end_dt, firmware_version)
    hit = _metrics_cache.get(key)
    if hit is None:
        return None
    cached_at, rows = hit
    if _time.time() - cached_at > _METRICS_CACHE_TTL_SECONDS:
        _metrics_cache.pop(key, None)
        return None
    return rows


def _metrics_cache_put(start_dt: datetime, end_dt: datetime, firmware_version: str | None, rows: list) -> None:
    import time as _time
    if len(_metrics_cache) > 64:
        # Drop the oldest; this cache is tiny by design
        oldest_key = min(_metrics_cache, key=lambda k: _metrics_cache[k][0])
        _metrics_cache.pop(oldest_key, None)
    _metrics_cache[_metrics_cache_key(start_dt, end_dt, firmware_version)] = (_time.time(), rows)


# ---------------------------------------------------------------------------
# Identity helpers
# ---------------------------------------------------------------------------

_MAC_STRIP_RE = re.compile(r"[^0-9a-fA-F]")


def normalize_mac(raw: str | None) -> str | None:
    if not raw:
        return None
    stripped = _MAC_STRIP_RE.sub("", raw).lower()
    if len(stripped) != 12:
        return None
    return stripped


# JSON-path expression that matches the expression index. Keep both in
# sync — see migration 20260420_0036.
_MAC_EXPR = "lower(raw_payload->'device_data'->'reported'->>'mac')"


def _device_ids_for_mac(db: Session, mac: str, limit: int = MAX_DEVICE_IDS_PER_MAC) -> list[str]:
    """Resolve a MAC to the distinct ``device_id`` hashes that have
    reported under it. Ordered by most-recent sample first so we keep
    the freshest association when we cap to ``limit``."""
    stmt = text(
        f"""
        SELECT device_id, MAX(sample_timestamp) AS last_seen
        FROM telemetry_stream_events
        WHERE {_MAC_EXPR} = :mac
        GROUP BY device_id
        ORDER BY last_seen DESC NULLS LAST
        LIMIT :lim
        """
    )
    return [r[0] for r in db.execute(stmt, {"mac": mac, "lim": limit}).all() if r[0]]


def _latest_stream_event_for_mac(db: Session, mac: str) -> TelemetryStreamEvent | None:
    stmt = text(
        f"""
        SELECT id FROM telemetry_stream_events
        WHERE {_MAC_EXPR} = :mac
        ORDER BY sample_timestamp DESC NULLS LAST
        LIMIT 1
        """
    )
    row_id = db.execute(stmt, {"mac": mac}).scalar_one_or_none()
    if row_id is None:
        return None
    return db.get(TelemetryStreamEvent, row_id)


def _trail_for_mac(db: Session, mac: str, limit: int = SHADOW_TRAIL_SAMPLES) -> list[TelemetryStreamEvent]:
    stmt = text(
        f"""
        SELECT id FROM telemetry_stream_events
        WHERE {_MAC_EXPR} = :mac
        ORDER BY sample_timestamp DESC NULLS LAST
        LIMIT :lim
        """
    )
    ids = [r[0] for r in db.execute(stmt, {"mac": mac, "lim": limit}).all()]
    if not ids:
        return []
    rows = db.execute(
        select(TelemetryStreamEvent).where(TelemetryStreamEvent.id.in_(ids))
    ).scalars().all()
    # Order by timestamp ASC for charting
    rows.sort(key=lambda r: r.sample_timestamp or datetime.min.replace(tzinfo=timezone.utc))
    return rows


def _observations_summary(db: Session, mac: str) -> dict[str, Any]:
    stmt = (
        select(AppSideDeviceObservation)
        .where(AppSideDeviceObservation.mac_normalized == mac)
        .order_by(desc(AppSideDeviceObservation.observed_at))
        .limit(25)
    )
    rows = db.execute(stmt).scalars().all()
    if not rows:
        return {"count": 0}
    latest = rows[0]
    user_keys = {r.user_key for r in rows if r.user_key}
    sources = {r.source for r in rows if r.source}
    return {
        "count": len(rows),
        "latest_observed_at": latest.observed_at.isoformat() if latest.observed_at else None,
        "self_reported_firmware_version": latest.firmware_version,
        "controller_model": latest.controller_model,
        "app_version": latest.app_version,
        "phone_os": latest.phone_os,
        "phone_os_version": latest.phone_os_version,
        "phone_brand": latest.phone_brand,
        "phone_model": latest.phone_model,
        "user_keys": sorted(user_keys),
        "sources": sorted(sources),
    }


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _serialize_stream_event(e: TelemetryStreamEvent | None) -> dict[str, Any] | None:
    if e is None:
        return None
    return {
        "sample_timestamp": e.sample_timestamp.isoformat() if e.sample_timestamp else None,
        "stream_event_name": e.stream_event_name,
        "engaged": bool(e.engaged),
        "firmware_version": e.firmware_version,
        "grill_type": e.grill_type,
        "target_temp": e.target_temp,
        "current_temp": e.current_temp,
        "heating": e.heating,
        "intensity": e.intensity,
        "rssi": e.rssi,
        "error_codes": list(e.error_codes_json or []),
    }


def _serialize_session(s: TelemetrySession) -> dict[str, Any]:
    return {
        "source_event_id": s.source_event_id,
        "session_id": s.session_id,
        "grill_type": s.grill_type,
        "firmware_version": s.firmware_version,
        "target_temp": s.target_temp,
        "session_start": s.session_start.isoformat() if s.session_start else None,
        "session_end": s.session_end.isoformat() if s.session_end else None,
        "session_duration_seconds": s.session_duration_seconds,
        "disconnect_events": s.disconnect_events,
        "manual_overrides": s.manual_overrides,
        "error_count": s.error_count,
        "error_codes": s.error_codes_json or [],
        "temp_stability_score": s.temp_stability_score,
        "time_to_stabilization_seconds": s.time_to_stabilization_seconds,
        "firmware_health_score": s.firmware_health_score,
        "session_reliability_score": s.session_reliability_score,
        "cook_success": bool(s.cook_success),
        "cook_intent": s.cook_intent,
        "cook_outcome": s.cook_outcome,
        "held_target": s.held_target,
        "in_control_pct": s.in_control_pct,
        "max_overshoot_f": s.max_overshoot_f,
        "max_undershoot_f": s.max_undershoot_f,
    }


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

@router.get("/device/lookup")
def device_lookup(
    query: str = Query(..., min_length=3, description="MAC (any separators) or email/user_key"),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    q = query.strip()
    mac = normalize_mac(q)
    macs: list[str] = []

    if mac:
        macs = [mac]
    else:
        like = f"%{q.lower()}%"
        stmt = (
            select(AppSideDeviceObservation.mac_normalized)
            .where(
                AppSideDeviceObservation.mac_normalized.isnot(None),
                func.lower(AppSideDeviceObservation.user_key).like(like),
            )
            .distinct()
            .limit(25)
        )
        macs = [m for (m,) in db.execute(stmt).all() if m]

    devices: list[dict[str, Any]] = []
    for m in macs:
        latest = _latest_stream_event_for_mac(db, m)
        device_ids = _device_ids_for_mac(db, m)
        session_count = 0
        if device_ids:
            session_count = db.execute(
                select(func.count(TelemetrySession.id)).where(TelemetrySession.device_id.in_(device_ids))
            ).scalar() or 0
        obs = _observations_summary(db, m)
        devices.append({
            "mac": m,
            "latest_stream_event": _serialize_stream_event(latest),
            "session_count": int(session_count),
            "app_side": obs,
            "device_id_count": len(device_ids),
        })

    return {"query": q, "resolved_as": "mac" if mac else "user_key", "devices": devices}


# ---------------------------------------------------------------------------
# Device detail
# ---------------------------------------------------------------------------

def _require_mac(mac: str) -> str:
    normalized = normalize_mac(mac)
    if not normalized:
        raise HTTPException(status_code=400, detail="mac must be 12 hex characters (any separators allowed)")
    return normalized


@router.get("/device/{mac}/shadow")
def device_shadow(mac: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    m = _require_mac(mac)
    event = _latest_stream_event_for_mac(db, m)
    now = datetime.now(timezone.utc)
    age_seconds: int | None = None
    if event and event.sample_timestamp:
        age_seconds = int((now - event.sample_timestamp).total_seconds())
    return {
        "mac": m,
        "event": _serialize_stream_event(event),
        "age_seconds": age_seconds,
        "fetched_at": now.isoformat(),
    }


@router.get("/device/{mac}/active-cook")
def device_active_cook(mac: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    m = _require_mac(mac)
    latest = _latest_stream_event_for_mac(db, m)
    now = datetime.now(timezone.utc)
    active = False
    if latest and latest.sample_timestamp:
        age = (now - latest.sample_timestamp).total_seconds()
        active = age <= ACTIVE_COOK_WINDOW_SECONDS and (bool(latest.engaged) or bool(latest.heating))

    trail: list[dict[str, Any]] = []
    if active:
        trail = [_serialize_stream_event(e) for e in _trail_for_mac(db, m, SHADOW_TRAIL_SAMPLES)]

    last_session = None
    if not active:
        device_ids = _device_ids_for_mac(db, m)
        if device_ids:
            sess = db.execute(
                select(TelemetrySession)
                .where(TelemetrySession.device_id.in_(device_ids))
                .order_by(desc(TelemetrySession.session_start))
                .limit(1)
            ).scalar_one_or_none()
            if sess:
                last_session = _serialize_session(sess)

    return {
        "mac": m,
        "active": active,
        "trail": trail,
        "latest_event": _serialize_stream_event(latest),
        "last_completed_session": last_session,
    }


@router.get("/device/{mac}/cook-timeline")
def device_cook_timeline(
    mac: str,
    lookback_hours: int = Query(24, ge=1, le=168),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Time-series chart payload for a device's current (or most-recent)
    cook. Walks the stream history back from now to find the first
    sample >= 140°F (live-fire threshold) in the current engaged window.
    The timeline returned runs from that cook_start through now (for
    active cooks) or through the last sample >= 140°F (for completed).

    Includes current_temp, target_temp, and intensity per sample so the
    UI can render a temp+target+fan chart and also show the moment the
    user changed their target mid-cook (``target_set_at``).
    """
    m = _require_mac(mac)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    stmt = text(
        f"""
        SELECT sample_timestamp, current_temp, target_temp, intensity, engaged
        FROM telemetry_stream_events
        WHERE {_MAC_EXPR} = :mac
          AND sample_timestamp >= :cutoff
        ORDER BY sample_timestamp ASC
        """
    )
    rows = db.execute(stmt, {"mac": m, "cutoff": cutoff}).all()
    if not rows:
        return {"mac": m, "cook_start_ts": None, "cook_end_ts": None, "points": [], "target_set_at": None}

    LIVE_FIRE_F = 140.0
    # Find the LAST cook window: scan forward, identify the most recent
    # transition into fire (>=140) and the ending transition out (<140).
    cook_start_idx: Optional[int] = None
    cook_end_idx: Optional[int] = None
    for i, r in enumerate(rows):
        t = r.current_temp
        if t is None:
            continue
        if t >= LIVE_FIRE_F:
            if cook_start_idx is None:
                cook_start_idx = i
            cook_end_idx = i  # keep extending while temp stays ≥140
        else:
            if cook_start_idx is not None and cook_end_idx is not None and i > cook_end_idx:
                # Temp dropped below 140 after a cook — check if cook ended
                # (require 5+ consecutive sub-140 samples to consider it ended).
                tail = rows[cook_end_idx + 1 : i + 1]
                if len(tail) >= 5 and all((s.current_temp or 0) < LIVE_FIRE_F for s in tail):
                    # Cook ended. If there's a later cook, the outer loop finds it.
                    pass

    if cook_start_idx is None:
        # No cook in window — return latest samples as context
        return {"mac": m, "cook_start_ts": None, "cook_end_ts": None, "points": [], "target_set_at": None}

    # Trim to the cook window
    cook_points = rows[cook_start_idx : cook_end_idx + 1]
    # Find target_set_at: last timestamp where target_temp changed vs prior sample
    target_set_at = None
    prior_target = None
    for r in rows:
        if r.target_temp is None:
            continue
        if prior_target is None:
            prior_target = r.target_temp
            target_set_at = r.sample_timestamp
            continue
        if abs(float(r.target_temp) - float(prior_target)) > 0.5:
            target_set_at = r.sample_timestamp
            prior_target = r.target_temp

    points = [
        {
            "ts": r.sample_timestamp.isoformat() if r.sample_timestamp else None,
            "current_temp": float(r.current_temp) if r.current_temp is not None else None,
            "target_temp": float(r.target_temp) if r.target_temp is not None else None,
            "intensity": float(r.intensity) if r.intensity is not None else None,
            "engaged": bool(r.engaged) if r.engaged is not None else None,
        }
        for r in cook_points
    ]
    cook_start_ts = cook_points[0].sample_timestamp if cook_points else None
    cook_end_ts = cook_points[-1].sample_timestamp if cook_points else None
    now = datetime.now(timezone.utc)
    # If the last cook sample is within 10 minutes of now AND still >=140,
    # treat the cook as active (ongoing).
    is_active = False
    if cook_end_ts:
        is_active = (now - cook_end_ts).total_seconds() <= 600 and cook_points and cook_points[-1].current_temp is not None and cook_points[-1].current_temp >= LIVE_FIRE_F
    return {
        "mac": m,
        "cook_start_ts": cook_start_ts.isoformat() if cook_start_ts else None,
        "cook_end_ts": cook_end_ts.isoformat() if cook_end_ts else None,
        "is_active": is_active,
        "target_set_at": target_set_at.isoformat() if target_set_at else None,
        "live_fire_threshold_f": LIVE_FIRE_F,
        "points": points,
    }


@router.get("/device/{mac}/sessions")
def device_sessions(
    mac: str,
    limit: int = Query(DEFAULT_SESSION_LIMIT, ge=1, le=200),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    m = _require_mac(mac)
    device_ids = _device_ids_for_mac(db, m)
    if not device_ids:
        return {"mac": m, "count": 0, "sessions": []}
    sessions = db.execute(
        select(TelemetrySession)
        .where(TelemetrySession.device_id.in_(device_ids))
        .order_by(desc(TelemetrySession.session_start))
        .limit(limit)
    ).scalars().all()
    return {
        "mac": m,
        "count": len(sessions),
        "sessions": [_serialize_session(s) for s in sessions],
    }


@router.get("/device/{mac}/summary")
def device_summary(mac: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    m = _require_mac(mac)
    latest = _latest_stream_event_for_mac(db, m)
    device_ids = _device_ids_for_mac(db, m)
    session_count = 0
    if device_ids:
        session_count = db.execute(
            select(func.count(TelemetrySession.id)).where(TelemetrySession.device_id.in_(device_ids))
        ).scalar() or 0
    obs = _observations_summary(db, m)

    # Beta/alpha/gamma cohort rows are keyed by ``device_id`` in
    # ``beta_cohort_members`` — check every resolved id.
    cohorts: list[dict[str, Any]] = []
    if device_ids:
        cohort_rows = db.execute(
            select(BetaCohortMember, FirmwareRelease)
            .join(FirmwareRelease, BetaCohortMember.release_id == FirmwareRelease.id)
            .where(BetaCohortMember.device_id.in_(device_ids))
            .order_by(desc(BetaCohortMember.invited_at))
        ).all()
        cohorts = [
            {
                "release_id": r.id,
                "release_version": r.version,
                "release_title": r.title,
                "state": c.state,
                "invited_at": c.invited_at.isoformat() if c.invited_at else None,
                "opted_in_at": c.opted_in_at.isoformat() if c.opted_in_at else None,
                "ota_pushed_at": c.ota_pushed_at.isoformat() if c.ota_pushed_at else None,
                "verdict": (c.verdict_json or {}).get("verdict"),
            }
            for (c, r) in cohort_rows
        ]

    return {
        "mac": m,
        "latest_stream_event": _serialize_stream_event(latest),
        "session_count": int(session_count),
        "app_side": obs,
        "cohorts": cohorts,
        "device_id_count": len(device_ids),
    }


# ---------------------------------------------------------------------------
# Program overview (top of hub)
# ---------------------------------------------------------------------------

def _build_firmware_overview_payload(db: Session) -> dict[str, Any]:
    """Pure builder — used by both the HTTP endpoint and the Tier 2
    cache registration in app.services.cache_builders."""
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    rows = db.execute(
        select(
            TelemetryStreamEvent.firmware_version,
            func.count(func.distinct(TelemetryStreamEvent.device_id)).label("devices"),
        )
        .where(TelemetryStreamEvent.sample_timestamp >= since)
        .group_by(TelemetryStreamEvent.firmware_version)
        .order_by(desc("devices"))
    ).all()
    distribution = [
        {"firmware_version": v or "unknown", "devices": int(n)}
        for (v, n) in rows
    ]
    total = sum(d["devices"] for d in distribution)
    for d in distribution:
        d["pct"] = round((d["devices"] / total) * 100, 1) if total else 0.0
    return {
        "window_hours": 24,
        "active_devices": total,
        "firmware_distribution": distribution,
    }


@router.get("/overview")
def overview(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Cache-first via Tier 2 aggregate_cache. On cold cache (fresh
    deploy), compute synchronously + populate. Subsequent requests hit
    the materialized row in <20 ms. The 15-min scheduler keeps it fresh."""
    from app.services import aggregate_cache
    import app.services.cache_builders  # noqa: F401 — registers builders
    from app.services.cache_builders import FIRMWARE_OVERVIEW_KEY
    entry = aggregate_cache.get(db, FIRMWARE_OVERVIEW_KEY)
    source = "cache"
    if entry is None:
        entry = aggregate_cache.build_if_missing(db, FIRMWARE_OVERVIEW_KEY)
        source = "live"
    if entry is None:
        return _build_firmware_overview_payload(db)
    payload = dict(entry.payload)
    payload["cache_info"] = {
        "key": entry.key,
        "computed_at": entry.computed_at.isoformat(),
        "duration_ms": entry.duration_ms,
        "age_seconds": entry.age_seconds(),
        "source": source,
    }
    return payload


# ---------------------------------------------------------------------------
# Overview metrics (cook success, in-control, disconnects, firmware split)
# ---------------------------------------------------------------------------


def _parse_date(raw: str | None, fallback: datetime) -> datetime:
    if not raw:
        return fallback
    try:
        # Accept "YYYY-MM-DD" or full ISO.
        if len(raw) == 10:
            return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date: {raw!r}")


@router.get("/overview/metrics")
def overview_metrics(
    start: str | None = Query(default=None, description="ISO date or datetime (UTC). Default: end - 7d."),
    end: str | None = Query(default=None, description="ISO date or datetime (UTC). Default: now."),
    firmware_version: str | None = Query(default=None),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    from app.services.product_taxonomy import classify_product

    # Cache-first on the default 7-day view (the one the Product
    # Engineering page hits on every load). Custom windows or firmware
    # filters skip this and go straight to live compute + the tiny TTL
    # cache further down.
    if start is None and end is None and firmware_version is None:
        from app.services import aggregate_cache
        import app.services.cache_builders  # noqa: F401 — registers builders
        from app.services.cache_builders import FIRMWARE_METRICS_7D_KEY
        entry = aggregate_cache.get(db, FIRMWARE_METRICS_7D_KEY)
        source = "cache"
        if entry is None:
            entry = aggregate_cache.build_if_missing(db, FIRMWARE_METRICS_7D_KEY)
            source = "live"
        if entry is not None:
            payload = dict(entry.payload)
            payload["cache_info"] = {
                "key": entry.key,
                "computed_at": entry.computed_at.isoformat(),
                "duration_ms": entry.duration_ms,
                "age_seconds": entry.age_seconds(),
                "source": source,
            }
            return payload

    now = datetime.now(timezone.utc)
    end_dt = _parse_date(end, now)
    start_dt = _parse_date(start, end_dt - timedelta(days=7))
    if start_dt >= end_dt:
        raise HTTPException(status_code=400, detail="start must be before end")

    session_filters = [
        TelemetrySession.session_start >= start_dt,
        TelemetrySession.session_start < end_dt,
    ]
    if firmware_version:
        session_filters.append(TelemetrySession.firmware_version == firmware_version)

    agg_row = db.execute(
        select(
            func.count(TelemetrySession.id).label("sessions"),
            func.sum(case((TelemetrySession.cook_success.is_(True), 1), else_=0)).label("successes"),
            func.avg(TelemetrySession.in_control_pct).label("avg_in_control"),
            func.sum(TelemetrySession.disconnect_events).label("disconnect_events"),
            func.count(func.distinct(TelemetrySession.device_id)).label("devices"),
        ).where(*session_filters)
    ).one()

    sessions = int(agg_row.sessions or 0)
    successes = int(agg_row.successes or 0)
    avg_in_control = float(agg_row.avg_in_control) if agg_row.avg_in_control is not None else None
    disconnect_events = int(agg_row.disconnect_events or 0)
    devices = int(agg_row.devices or 0)

    success_rate = (successes / sessions) if sessions else None
    disconnect_rate_per_session = (disconnect_events / sessions) if sessions else None

    # TelemetrySession is fed by a DynamoDB scanner that has been
    # lagging behind the live stream (sessions stopped updating on
    # 2026-04-09 even though stream ingest kept producing events).
    # Rather than silently show zeroes, surface when it went stale
    # and when we last saw a real session so the UI can be honest.
    latest_session_ts = db.execute(select(func.max(TelemetrySession.session_start))).scalar()
    sessions_source = "telemetry_sessions"
    sessions_stale = False
    if sessions == 0 and latest_session_ts is not None and latest_session_ts < start_dt:
        sessions_stale = True

    # Combined distribution query — one pass over telemetry_stream_events
    # instead of two. Each query previously did count(distinct device_id)
    # over ~2.7M rows per week at ~11s each (22s combined). Grouping by
    # (grill_type, firmware_version) once and deriving both distributions
    # in Python drops the pair to ~11s, and the module-level cache below
    # makes every subsequent hit inside the TTL window instant.
    combined_rows = _metrics_cache_get(start_dt, end_dt, firmware_version)
    if combined_rows is None:
        combined_rows = db.execute(
            select(
                TelemetryStreamEvent.grill_type,
                TelemetryStreamEvent.firmware_version,
                func.count(func.distinct(TelemetryStreamEvent.device_id)).label("devices"),
            )
            .where(
                TelemetryStreamEvent.sample_timestamp >= start_dt,
                TelemetryStreamEvent.sample_timestamp < end_dt,
            )
            .group_by(TelemetryStreamEvent.grill_type, TelemetryStreamEvent.firmware_version)
        ).all()
        _metrics_cache_put(start_dt, end_dt, firmware_version, combined_rows)

    firmware_counts: dict[str | None, int] = {}
    product_counts: dict[str, int] = {}
    for grill_type_val, fw_val, n in combined_rows:
        n_int = int(n or 0)
        firmware_counts[fw_val] = firmware_counts.get(fw_val, 0) + n_int
        family = classify_product(grill_type_val, fw_val)
        product_counts[family] = product_counts.get(family, 0) + n_int

    dist_total = sum(firmware_counts.values())
    firmware_distribution = [
        {
            "firmware_version": v or "unknown",
            "devices": int(n),
            "pct": round((int(n) / dist_total) * 100, 1) if dist_total else 0.0,
        }
        for v, n in sorted(firmware_counts.items(), key=lambda kv: kv[1], reverse=True)
    ]
    pf_total = sum(product_counts.values())
    product_distribution = [
        {
            "product": family,
            "devices": count,
            "pct": round((count / pf_total) * 100, 1) if pf_total else 0.0,
        }
        for family, count in sorted(product_counts.items(), key=lambda kv: kv[1], reverse=True)
    ]

    return {
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "firmware_version": firmware_version,
        "sessions": sessions,
        "sessions_source": sessions_source,
        "sessions_stale": sessions_stale,
        "sessions_latest_ts": latest_session_ts.isoformat() if latest_session_ts else None,
        "devices": devices,
        "cook_success_rate": success_rate,
        "avg_in_control_pct": avg_in_control,
        "disconnect_events": disconnect_events,
        "disconnect_rate_per_session": disconnect_rate_per_session,
        "firmware_distribution": firmware_distribution,
        "product_distribution": product_distribution,
        "active_devices_window": dist_total,
    }


# ---------------------------------------------------------------------------
# App control review (commanded vs reported)
#
# We don't have a separate "app sent this command" stream — the app
# writes the desired state via AWS IoT shadow, the grill accepts it and
# echoes it back in its ``reported`` block. So "commanded" here means
# the target the grill is honoring (``heat.t2.trgt``, ``probes.p2.trgt``)
# and "actual" means what it's reporting (``mainTemp``, probe temps).
# The gap is what the PID loop is working against.
# ---------------------------------------------------------------------------


_CONTROL_WINDOW_SECONDS = 600  # 10 min
_IN_CONTROL_GAP_F = 15.0  # ± °F counts as "in control"


def _extract_control_signals(raw_payload: dict | None) -> dict[str, Any]:
    """Pull commanded + reported fields out of a stream-event payload.

    Handles missing/partial payloads gracefully — every caller must
    expect ``None`` for any individual field.
    """
    if not isinstance(raw_payload, dict):
        return {}
    reported = ((raw_payload.get("device_data") or {}).get("reported")) or {}
    heat = (reported.get("heat") or {}).get("t2") or {}
    probes = reported.get("probes") or {}

    main_temp = reported.get("mainTemp")
    target = heat.get("trgt")
    gap = None
    if isinstance(main_temp, (int, float)) and isinstance(target, (int, float)):
        gap = float(main_temp) - float(target)

    probe_signals = []
    for key, p in probes.items():
        if not isinstance(p, dict):
            continue
        probe_signals.append({
            "probe": key,
            "current_temp": p.get("temp"),
            "target_temp": p.get("trgt"),
        })

    return {
        "target_temp": target,
        "current_temp": main_temp,
        "gap_f": gap,
        "intensity": heat.get("intensity"),
        "heating": heat.get("heating"),
        "engaged": reported.get("engaged"),
        "paused": reported.get("paused"),
        "door_open": reported.get("doorOpn"),
        "power_on": reported.get("pwrOn"),
        "fahrenheit": reported.get("fah"),
        "rssi": reported.get("RSSI"),
        "firmware_version": reported.get("vers"),
        "model": reported.get("model"),
        "errors": reported.get("errors") or [],
        "probes": probe_signals,
    }


@router.get("/device/{mac}/control-signals")
def device_control_signals(mac: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    m = _require_mac(mac)
    event = _latest_stream_event_for_mac(db, m)
    if event is None:
        return {"mac": m, "event_at": None, "signals": None}
    signals = _extract_control_signals(event.raw_payload)
    return {
        "mac": m,
        "event_at": event.sample_timestamp.isoformat() if event.sample_timestamp else None,
        "firmware_version": event.firmware_version,
        "signals": signals,
    }


@router.get("/fleet/control-health")
def fleet_control_health(
    sort: str = Query("gap_abs", pattern="^(gap_abs|gap|target|intensity|firmware|sample_ts|state|cook_elapsed|product)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    state: Optional[str] = Query(None),
    product: Optional[str] = Query(None, description="Filter by product family: 'Weber Kettle', 'Huntsman', 'Giant Huntsman', 'Unknown'"),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Fleet-wide snapshot that uses the TIME-AWARE cook state classifier
    instead of a naive temp-gap threshold.

    States returned per device: ramping_up | in_control | out_of_control |
    cooling_down | manual_mode | error | idle. Only ``out_of_control`` and
    ``error`` count as anomalies — ramping-up and cooling-down grills are
    doing exactly what the user asked for and no longer get flagged.

    Also returns ``cook_start_ts`` (first sample where pit temp crossed
    140°F in this engagement window) and ``cook_elapsed_seconds`` so the
    UI can distinguish "engaged with real fire" from "engaged, no heat yet."
    """
    from app.services.product_taxonomy import classify_product

    now = datetime.now(timezone.utc)
    # 30 min window — any longer risks pulling a multi-million-row
    # stream slab into memory on the app server. The live-fire onset is
    # still useful within this window: a cook that's been running for
    # 4 hours will still show its >=140°F crossing somewhere in the
    # last 30 min because it's sustained; only a freshly-lit cook with
    # onset in the last minute won't have reached 140°F yet, which is
    # exactly the case we WANT to show as "ramping up, no fire yet."
    window_s = 30 * 60
    cutoff = now - timedelta(seconds=window_s)

    events = db.execute(
        select(TelemetryStreamEvent)
        .where(TelemetryStreamEvent.sample_timestamp >= cutoff)
        .order_by(TelemetryStreamEvent.device_id, TelemetryStreamEvent.sample_timestamp)
    ).scalars().all()

    by_device: dict[str, list[TelemetryStreamEvent]] = {}
    for ev in events:
        by_device.setdefault(ev.device_id, []).append(ev)

    try:
        baseline_lookup = get_baseline_lookup(db)
    except Exception:
        baseline_lookup = None

    devices: list[dict[str, Any]] = []
    tallies: dict[str, int] = {s: 0 for s in cook_state.ALL_STATES}
    product_tallies: dict[str, int] = {}
    for device_id, dev_events in by_device.items():
        r = cook_state.classify_from_events(dev_events, baseline_lookup=baseline_lookup, now=now)
        tallies[r.state] = tallies.get(r.state, 0) + 1
        latest = dev_events[-1]
        reported = ((latest.raw_payload or {}).get("device_data") or {}).get("reported") or {}
        mac = (reported.get("mac") or "").lower() or None
        grill_type = latest.grill_type
        product_family = classify_product(grill_type, latest.firmware_version)
        product_tallies[product_family] = product_tallies.get(product_family, 0) + 1
        # target_set_at: scan the event window backward to find the most
        # recent target_temp change. Cheap because each device has <=30
        # events in the 30-min window.
        target_set_at: Optional[datetime] = None
        prior_target = None
        for ev in dev_events:
            if ev.target_temp is None:
                continue
            if prior_target is None:
                prior_target = ev.target_temp
                target_set_at = ev.sample_timestamp
                continue
            if abs(float(ev.target_temp) - float(prior_target)) > 0.5:
                target_set_at = ev.sample_timestamp
                prior_target = ev.target_temp
        device_row = cook_state.result_to_dict(
            r, mac=mac, device_id=device_id,
            firmware_version=latest.firmware_version,
            grill_type=grill_type, product=product_family,
        )
        device_row["target_set_at"] = target_set_at.isoformat() if target_set_at else None
        devices.append(device_row)

    if state and state in cook_state.ALL_STATES:
        devices = [d for d in devices if d["state"] == state]
    if product:
        devices = [d for d in devices if d.get("product") == product]

    def _sort_key(d: dict[str, Any]):
        if sort == "gap_abs":
            v = d.get("gap_f")
            return abs(v) if isinstance(v, (int, float)) else -1
        if sort == "gap":
            v = d.get("gap_f")
            return v if isinstance(v, (int, float)) else 0
        if sort == "target":
            v = d.get("target_temp")
            return v if isinstance(v, (int, float)) else 0
        if sort == "intensity":
            v = d.get("intensity")
            return v if isinstance(v, (int, float)) else 0
        if sort == "firmware":
            return d.get("firmware_version") or ""
        if sort == "sample_ts":
            return d.get("sample_timestamp") or ""
        if sort == "state":
            return d.get("state") or ""
        if sort == "cook_elapsed":
            v = d.get("cook_elapsed_seconds")
            return v if isinstance(v, (int, float)) else -1
        if sort == "product":
            return d.get("product") or ""
        return 0

    devices.sort(key=_sort_key, reverse=(sort_dir == "desc"))

    total = len(devices)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    start_idx = (page - 1) * per_page
    page_devices = devices[start_idx : start_idx + per_page]

    active = tallies.get(cook_state.STATE_IN_CONTROL, 0) + tallies.get(cook_state.STATE_OUT_OF_CONTROL, 0) + tallies.get(cook_state.STATE_RAMPING_UP, 0) + tallies.get(cook_state.STATE_MANUAL_MODE, 0)
    anomalous = tallies.get(cook_state.STATE_OUT_OF_CONTROL, 0) + tallies.get(cook_state.STATE_ERROR, 0)

    return {
        "window_seconds": window_s,
        "total_reporting_devices": len(by_device),
        "active_cooks": active,
        "tallies": tallies,
        "product_tallies": product_tallies,
        "anomalous_count": anomalous,
        "baseline_driven": baseline_lookup is not None,
        "devices": page_devices,
        "page": page,
        "per_page": per_page,
        "total_filtered": total,
        "total_pages": total_pages,
        "fetched_at": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# Cook behavior knowledge base — the "encyclopedia"
# ---------------------------------------------------------------------------


@router.get("/cook-behavior/baselines")
def cook_behavior_baselines(
    firmware_version: Optional[str] = Query(None),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Return the learned baselines per target-temp band.

    If ``firmware_version`` is provided, returns only that firmware's
    bins (with fallback to rollup rows where the firmware has too few
    samples). Otherwise returns the all-firmware rollup.
    """
    from app.models import CookBehaviorBaseline
    q = select(CookBehaviorBaseline)
    if firmware_version:
        q = q.where(
            (CookBehaviorBaseline.firmware_version == firmware_version)
            | (CookBehaviorBaseline.firmware_version.is_(None))
        )
    else:
        q = q.where(CookBehaviorBaseline.firmware_version.is_(None))
    rows = db.execute(q.order_by(CookBehaviorBaseline.target_temp_band)).scalars().all()

    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "target_temp_band": r.target_temp_band,
            "firmware_version": r.firmware_version,
            "baseline_version": r.baseline_version,
            "sample_size": r.sample_size,
            "ramp_time_p10": r.ramp_time_p10,
            "ramp_time_p50": r.ramp_time_p50,
            "ramp_time_p90": r.ramp_time_p90,
            "steady_fan_p10": r.steady_fan_p10,
            "steady_fan_p50": r.steady_fan_p50,
            "steady_fan_p90": r.steady_fan_p90,
            "steady_temp_stddev_p50": r.steady_temp_stddev_p50,
            "steady_temp_stddev_p90": r.steady_temp_stddev_p90,
            "cool_down_rate_p50": r.cool_down_rate_p50,
            "typical_duration_p50": r.typical_duration_p50,
            "computed_at": r.computed_at.isoformat() if r.computed_at else None,
        })
    return {
        "baselines": out,
        "firmware_version": firmware_version,
    }


@router.get("/cook-behavior/backtest")
def cook_behavior_backtest(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Latest self-evaluation run: per (band, metric) coverage against
    p10-p90 bands. Drift shows as coverage << 80%."""
    from app.services.cook_behavior_backtest import load_latest_drift
    rows = load_latest_drift(db)
    return {"rows": rows}


@router.post("/cook-behavior/rebuild")
def cook_behavior_rebuild(
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Manual trigger — owner-only. Rebuilds baselines + runs backtest
    end-to-end. Normally runs nightly at 08:30 UTC via the scheduler."""
    user = _require_session_user(request, db)
    if (user.email or "").lower() != "joseph@spidergrills.com":
        raise HTTPException(status_code=403, detail="Owner only")
    from app.services.cook_behavior_backtest import run_cook_behavior_backtest
    from app.services.cook_behavior_baselines import rebuild_cook_behavior_baselines
    try:
        bt = run_cook_behavior_backtest(db)
    except Exception as e:
        bt = {"error": str(e)}
        db.rollback()
    rb = rebuild_cook_behavior_baselines(db)
    return {"backtest": bt, "rebuild": rb}


@router.get("/cook-behavior/ticket/{ticket_id}")
def cook_behavior_ticket_correlation(
    ticket_id: str,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Fetch the pre-computed Freshdesk↔cook correlation for a ticket.

    Used by support surfaces to show "this ticket was opened during a
    cook that overshot by 85°F"."""
    from app.models import FreshdeskCookCorrelation
    row = db.execute(
        select(FreshdeskCookCorrelation).where(FreshdeskCookCorrelation.ticket_id == ticket_id)
    ).scalars().first()
    if row is None:
        return {"ticket_id": ticket_id, "correlation": None}
    return {
        "ticket_id": ticket_id,
        "correlation": {
            "mac": row.mac_normalized,
            "ticket_created_at": row.ticket_created_at.isoformat() if row.ticket_created_at else None,
            "window_start": row.window_start.isoformat() if row.window_start else None,
            "window_end": row.window_end.isoformat() if row.window_end else None,
            "sessions_matched": row.sessions_matched,
            "evidence": row.evidence_json,
            "computed_at": row.computed_at.isoformat() if row.computed_at else None,
        },
    }


# ---------------------------------------------------------------------------
# Per-user device recents + nicknames
# ---------------------------------------------------------------------------

RECENTS_LIMIT = 30


def _require_session_user(request: Request, db: Session):
    user = get_user_from_request(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Dashboard session required")
    return user


def _serialize_recent(row: FirmwareDeviceRecent) -> dict[str, Any]:
    return {
        "mac": row.mac,
        "nickname": row.nickname,
        "last_viewed_at": row.last_viewed_at.isoformat() if row.last_viewed_at else None,
    }


class RecentUpsertBody(BaseModel):
    mac: str = Field(..., min_length=1, max_length=64)


class RecentNicknameBody(BaseModel):
    nickname: Optional[str] = Field(default=None, max_length=128)


@router.get("/device/recents")
def list_recents(request: Request, db: Session = Depends(db_session)) -> dict[str, Any]:
    user = _require_session_user(request, db)
    rows = db.execute(
        select(FirmwareDeviceRecent)
        .where(FirmwareDeviceRecent.user_id == user.id)
        .order_by(desc(FirmwareDeviceRecent.last_viewed_at))
        .limit(RECENTS_LIMIT)
    ).scalars().all()
    return {"recents": [_serialize_recent(r) for r in rows]}


@router.post("/device/recents/upsert")
def upsert_recent(
    body: RecentUpsertBody,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    user = _require_session_user(request, db)
    mac = normalize_mac(body.mac)
    if mac is None:
        raise HTTPException(status_code=400, detail="Invalid MAC address")

    row = db.execute(
        select(FirmwareDeviceRecent).where(
            FirmwareDeviceRecent.user_id == user.id,
            FirmwareDeviceRecent.mac == mac,
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None:
        row = FirmwareDeviceRecent(user_id=user.id, mac=mac, last_viewed_at=now)
        db.add(row)
    else:
        row.last_viewed_at = now
    db.commit()
    db.refresh(row)
    return _serialize_recent(row)


@router.patch("/device/recents/{mac}")
def set_recent_nickname(
    mac: str,
    body: RecentNicknameBody,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    user = _require_session_user(request, db)
    m = normalize_mac(mac)
    if m is None:
        raise HTTPException(status_code=400, detail="Invalid MAC address")

    row = db.execute(
        select(FirmwareDeviceRecent).where(
            FirmwareDeviceRecent.user_id == user.id,
            FirmwareDeviceRecent.mac == m,
        )
    ).scalar_one_or_none()
    if row is None:
        # Auto-create so the user can tag a device without viewing it first.
        row = FirmwareDeviceRecent(user_id=user.id, mac=m)
        db.add(row)

    nickname = (body.nickname or "").strip() or None
    row.nickname = nickname
    db.commit()
    db.refresh(row)
    return _serialize_recent(row)


@router.delete("/device/recents/{mac}")
def delete_recent(
    mac: str,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    user = _require_session_user(request, db)
    m = normalize_mac(mac)
    if m is None:
        raise HTTPException(status_code=400, detail="Invalid MAC address")

    row = db.execute(
        select(FirmwareDeviceRecent).where(
            FirmwareDeviceRecent.user_id == user.id,
            FirmwareDeviceRecent.mac == m,
        )
    ).scalar_one_or_none()
    if row is not None:
        db.delete(row)
        db.commit()
    return {"ok": True, "mac": m}
