"""Firmware Hub — device drill-down, live shadow, session history, and
program overview (beta/alpha/gamma).

Phase 1 is view-only. All actual firmware *deploy* endpoints (OTA push,
cohort assignment, alpha promotion) will land in a later phase and will
be owner-gated the same way the ECR tracker is. For now this route only
exposes read paths so anyone with a dashboard session can troubleshoot a
device in the field.

Device identity convention:

  * ``mac_normalized`` — lowercase, hex-only (``fcb467f9b456``). Matches
    AWS IoT ``thingName`` and equals ``TelemetryStreamEvent.device_id``.
  * Lookup accepts either a free-form MAC (any separators, any case) or
    an email / user_key that we can resolve through
    ``AppSideDeviceObservation``.

Live shadow freshness is ~15s (AWS poll cadence). The UI should poll the
shadow endpoint on that cadence while a device detail view is open.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.models import (
    AppSideDeviceObservation,
    BetaCohortMember,
    FirmwareRelease,
    TelemetrySession,
    TelemetryStreamEvent,
)


logger = logging.getLogger(__name__)

ACTIVE_COOK_WINDOW_SECONDS = 120  # most-recent sample within 2m + engaged/heating = "live cook"
SHADOW_TRAIL_SAMPLES = 60         # ~15 min of 15s polling; enough for a temperature chart
DEFAULT_SESSION_LIMIT = 20

router = APIRouter(prefix="/api/firmware", tags=["firmware"])


# ---------------------------------------------------------------------------
# Identity helpers
# ---------------------------------------------------------------------------

_MAC_STRIP_RE = re.compile(r"[^0-9a-fA-F]")


def normalize_mac(raw: str | None) -> str | None:
    """Strip separators and lowercase. Returns None if the result is not
    a plausible 12-hex-char MAC so callers can fall through to email
    lookup without raising."""
    if not raw:
        return None
    stripped = _MAC_STRIP_RE.sub("", raw).lower()
    if len(stripped) != 12:
        return None
    return stripped


def _latest_app_observation(db: Session, mac: str) -> AppSideDeviceObservation | None:
    stmt = (
        select(AppSideDeviceObservation)
        .where(AppSideDeviceObservation.mac_normalized == mac)
        .order_by(desc(AppSideDeviceObservation.observed_at))
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def _observations_summary(db: Session, mac: str) -> dict[str, Any]:
    """Roll up what we know about this device from app-side observations —
    self-reported firmware, app version, phone, and what we last saw."""
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
    """Resolve a free-form identifier to one or more devices. Returns a
    list so an email that maps to multiple registered grills still works.

    Resolution order:
      1. If ``query`` normalizes to a 12-hex MAC, return that single device.
      2. Otherwise treat as email/user_key and scan
         ``app_side_device_observations`` for a case-insensitive contains
         match against ``user_key``.
    """
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
        latest_stream = db.execute(
            select(TelemetryStreamEvent)
            .where(TelemetryStreamEvent.device_id == m)
            .order_by(desc(TelemetryStreamEvent.sample_timestamp))
            .limit(1)
        ).scalar_one_or_none()
        session_count = db.execute(
            select(func.count(TelemetrySession.id)).where(TelemetrySession.device_id == m)
        ).scalar() or 0
        obs = _observations_summary(db, m)
        devices.append({
            "mac": m,
            "latest_stream_event": _serialize_stream_event(latest_stream),
            "session_count": int(session_count),
            "app_side": obs,
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
    """Latest telemetry stream event for a device. UI polls this on the
    15s AWS shadow cadence while a device view is open."""
    m = _require_mac(mac)
    event = db.execute(
        select(TelemetryStreamEvent)
        .where(TelemetryStreamEvent.device_id == m)
        .order_by(desc(TelemetryStreamEvent.sample_timestamp))
        .limit(1)
    ).scalar_one_or_none()
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
    """If the device has a recent sample with engaged=true or heating=true,
    return the last ``SHADOW_TRAIL_SAMPLES`` events as a temperature trail
    so the UI can chart a live cook. Otherwise return ``active=false`` and
    the most recent completed session for context."""
    m = _require_mac(mac)
    latest = db.execute(
        select(TelemetryStreamEvent)
        .where(TelemetryStreamEvent.device_id == m)
        .order_by(desc(TelemetryStreamEvent.sample_timestamp))
        .limit(1)
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    active = False
    if latest and latest.sample_timestamp:
        age = (now - latest.sample_timestamp).total_seconds()
        active = age <= ACTIVE_COOK_WINDOW_SECONDS and (bool(latest.engaged) or bool(latest.heating))

    trail: list[dict[str, Any]] = []
    if active:
        events = db.execute(
            select(TelemetryStreamEvent)
            .where(TelemetryStreamEvent.device_id == m)
            .order_by(desc(TelemetryStreamEvent.sample_timestamp))
            .limit(SHADOW_TRAIL_SAMPLES)
        ).scalars().all()
        # UI wants oldest → newest for charting
        trail = [_serialize_stream_event(e) for e in reversed(events)]

    last_session = None
    if not active:
        sess = db.execute(
            select(TelemetrySession)
            .where(TelemetrySession.device_id == m)
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
    """Recent cooking sessions for this device. Newest first."""
    m = _require_mac(mac)
    sessions = db.execute(
        select(TelemetrySession)
        .where(TelemetrySession.device_id == m)
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
    """Everything the drill-down view needs in one shot: identity,
    app-side observations, cohort memberships, session count, firmware
    version last seen live."""
    m = _require_mac(mac)
    latest = db.execute(
        select(TelemetryStreamEvent)
        .where(TelemetryStreamEvent.device_id == m)
        .order_by(desc(TelemetryStreamEvent.sample_timestamp))
        .limit(1)
    ).scalar_one_or_none()
    session_count = db.execute(
        select(func.count(TelemetrySession.id)).where(TelemetrySession.device_id == m)
    ).scalar() or 0
    obs = _observations_summary(db, m)

    cohort_rows = db.execute(
        select(BetaCohortMember, FirmwareRelease)
        .join(FirmwareRelease, BetaCohortMember.release_id == FirmwareRelease.id)
        .where(BetaCohortMember.device_id == m)
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
    }


# ---------------------------------------------------------------------------
# Program overview (top of hub)
# ---------------------------------------------------------------------------

@router.get("/overview")
def overview(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Fleet-wide firmware overview — version distribution (from the last
    24h of live stream events) + active devices count."""
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
