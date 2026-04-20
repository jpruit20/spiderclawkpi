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

@router.get("/overview")
def overview(db: Session = Depends(db_session)) -> dict[str, Any]:
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

    # Session-level aggregates
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

    # Firmware distribution over the window (based on stream events — same
    # shape as /overview, but windowed to the selected range).
    dist_rows = db.execute(
        select(
            TelemetryStreamEvent.firmware_version,
            func.count(func.distinct(TelemetryStreamEvent.device_id)).label("devices"),
        )
        .where(
            TelemetryStreamEvent.sample_timestamp >= start_dt,
            TelemetryStreamEvent.sample_timestamp < end_dt,
        )
        .group_by(TelemetryStreamEvent.firmware_version)
        .order_by(desc("devices"))
    ).all()
    dist_total = sum(int(n or 0) for (_, n) in dist_rows)
    firmware_distribution = [
        {
            "firmware_version": v or "unknown",
            "devices": int(n),
            "pct": round((int(n) / dist_total) * 100, 1) if dist_total else 0.0,
        }
        for (v, n) in dist_rows
    ]

    return {
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "firmware_version": firmware_version,
        "sessions": sessions,
        "devices": devices,
        "cook_success_rate": success_rate,
        "avg_in_control_pct": avg_in_control,
        "disconnect_events": disconnect_events,
        "disconnect_rate_per_session": disconnect_rate_per_session,
        "firmware_distribution": firmware_distribution,
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
def fleet_control_health(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Fleet-wide snapshot of who's currently cooking, who's in-control,
    and who's running hot or cold.

    Looks at each device's latest stream event in the last 10 minutes.
    "Engaged" = reported.engaged=true. "In-control" = |main - target| ≤
    ``_IN_CONTROL_GAP_F``. Returns both the tallies and the list of
    out-of-control devices for Agustin to drill into.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=_CONTROL_WINDOW_SECONDS)

    # Latest event per device_id in window.
    subq = (
        select(
            TelemetryStreamEvent.device_id,
            func.max(TelemetryStreamEvent.sample_timestamp).label("max_ts"),
        )
        .where(TelemetryStreamEvent.sample_timestamp >= cutoff)
        .group_by(TelemetryStreamEvent.device_id)
        .subquery()
    )
    latest_events = db.execute(
        select(TelemetryStreamEvent)
        .join(
            subq,
            (TelemetryStreamEvent.device_id == subq.c.device_id)
            & (TelemetryStreamEvent.sample_timestamp == subq.c.max_ts),
        )
    ).scalars().all()

    active_cooks = 0
    in_control = 0
    out_of_control: list[dict[str, Any]] = []
    total_reporting = len(latest_events)

    for ev in latest_events:
        signals = _extract_control_signals(ev.raw_payload)
        engaged = bool(signals.get("engaged"))
        if not engaged:
            continue
        active_cooks += 1
        gap = signals.get("gap_f")
        if isinstance(gap, (int, float)):
            if abs(gap) <= _IN_CONTROL_GAP_F:
                in_control += 1
            else:
                # Use reported MAC (not device_id) for the UI — MAC is the
                # user-visible id.
                reported = ((ev.raw_payload or {}).get("device_data") or {}).get("reported") or {}
                mac = (reported.get("mac") or "").lower() or None
                out_of_control.append({
                    "mac": mac,
                    "device_id": ev.device_id,
                    "target_temp": signals.get("target_temp"),
                    "current_temp": signals.get("current_temp"),
                    "gap_f": gap,
                    "intensity": signals.get("intensity"),
                    "firmware_version": signals.get("firmware_version"),
                    "sample_timestamp": ev.sample_timestamp.isoformat() if ev.sample_timestamp else None,
                })

    out_of_control.sort(key=lambda d: abs(d["gap_f"]) if d["gap_f"] is not None else 0, reverse=True)

    return {
        "window_seconds": _CONTROL_WINDOW_SECONDS,
        "in_control_gap_f": _IN_CONTROL_GAP_F,
        "total_reporting_devices": total_reporting,
        "active_cooks": active_cooks,
        "in_control": in_control,
        "out_of_control_count": len(out_of_control),
        "out_of_control_devices": out_of_control[:50],
        "fetched_at": now.isoformat(),
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
