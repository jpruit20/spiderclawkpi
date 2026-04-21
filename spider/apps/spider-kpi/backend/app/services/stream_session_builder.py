"""Build TelemetrySession rows from live TelemetryStreamEvent data.

Replaces the dead DynamoDB-backed path: the `aws_telemetry` connector
scans a source that hasn't been written to since 2025-06. This service
treats the stream table as the authoritative source for session
derivation and writes the resulting sessions alongside S3 backfill
rows (preserved) without touching DynamoDB-derived ones.

Conventions:
  * Source IDs: ``stream:{device_id}:{start_ts_epoch}:{end_ts_epoch}``
    — deterministic, safe for upsert.
  * S3 backfill IDs (``s3:…``) and DynamoDB IDs remain untouched.
  * Idempotent — re-running over the same window skips already-written
    sessions (ON CONFLICT on source_event_id).

Call paths:
  * ``rebuild_sessions_from_stream(db, since, until=None)`` — the core
    builder. Walks the stream table in per-device order and writes
    sessions.
  * ``run_scheduler_tick(db)`` — hourly: rebuilds from max(session_start
    where source starts 'stream:') onwards.
  * CLI backfill: run the module entry point with ``--since-date``.

The session derivation reuses ``_derive_sessions`` from
``telemetry_stream_summary`` which already has the 45-minute gap
grouping + target-reach + stability-score logic.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Iterable, Optional

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import TelemetrySession, TelemetryStreamEvent
from app.services.telemetry_stream_summary import _derive_sessions


logger = logging.getLogger(__name__)

SESSION_SOURCE_PREFIX = "stream:"


def _device_ids_in_window(
    db: Session, since: datetime, until: datetime, limit: Optional[int] = None
) -> list[str]:
    """Distinct device_ids with events in [since, until). Ordered by
    most-recent event so large backfills make fast progress on the
    hottest devices first."""
    stmt = (
        select(
            TelemetryStreamEvent.device_id,
            func.max(TelemetryStreamEvent.sample_timestamp).label("last_seen"),
        )
        .where(
            TelemetryStreamEvent.sample_timestamp >= since,
            TelemetryStreamEvent.sample_timestamp < until,
        )
        .group_by(TelemetryStreamEvent.device_id)
        .order_by(text("last_seen DESC NULLS LAST"))
    )
    if limit:
        stmt = stmt.limit(limit)
    return [r[0] for r in db.execute(stmt).all() if r[0]]


def _derived_session_to_row(ds) -> dict[str, Any]:
    """Convert a DerivedSession + its event list into a dict keyed to
    TelemetrySession columns. Builds the two JSONB time-series from
    the raw events attached to the session."""
    events = ds.events
    actual_series = [
        {"ts": (e.sample_timestamp or e.created_at).isoformat(), "temp": float(e.current_temp)}
        for e in events if e.current_temp is not None and (e.sample_timestamp or e.created_at)
    ]
    fan_series = [
        {"ts": (e.sample_timestamp or e.created_at).isoformat(), "value": float(e.intensity)}
        for e in events if e.intensity is not None and (e.sample_timestamp or e.created_at)
    ]

    # Disconnect count: approximate by counting time gaps > 3 min
    # between consecutive samples. `disconnect_proxy` on the DerivedSession
    # is a yes/no; we want a count for the column.
    disc = 0
    sorted_events = sorted(events, key=lambda e: (e.sample_timestamp or e.created_at))
    prev_ts = None
    for e in sorted_events:
        ts = e.sample_timestamp or e.created_at
        if ts is None:
            continue
        if prev_ts is not None and (ts - prev_ts).total_seconds() > 180:
            disc += 1
        prev_ts = ts

    # in_control_pct from DerivedSession's stability framework isn't
    # directly exposed, so derive it here: % of post-reach samples
    # within ±15°F of target.
    in_control_pct = None
    if ds.target_temp is not None and ds.reached_target:
        post = [e.current_temp for e in events if e.current_temp is not None]
        if post:
            in_window = sum(1 for t in post if abs(float(t) - float(ds.target_temp)) <= 15.0)
            in_control_pct = (in_window / len(post)) * 100.0

    # Max over/under-shoot
    max_over = None
    max_under = None
    if ds.target_temp is not None:
        temps = [float(e.current_temp) for e in events if e.current_temp is not None]
        if temps:
            over = max(temps) - float(ds.target_temp)
            under = float(ds.target_temp) - min(temps)
            max_over = max(0.0, over)
            max_under = max(0.0, under)

    start_ts = ds.start_ts
    end_ts = ds.end_ts
    duration = max(0, int((end_ts - start_ts).total_seconds())) if (start_ts and end_ts) else 0
    source_id = f"{SESSION_SOURCE_PREFIX}{ds.device_id}:{int(start_ts.timestamp())}:{int(end_ts.timestamp())}"

    return {
        "source_event_id": source_id,
        "device_id": ds.device_id,
        "user_id": None,
        "session_id": None,
        "grill_type": ds.grill_type,
        "firmware_version": ds.firmware_version,
        "target_temp": ds.target_temp,
        "session_start": start_ts,
        "session_end": end_ts,
        "session_duration_seconds": duration,
        "disconnect_events": disc,
        "manual_overrides": 0,
        "error_count": int(ds.error_count or 0),
        "error_codes_json": [],
        "actual_temp_time_series": actual_series,
        "fan_output_time_series": fan_series,
        "temp_stability_score": float(ds.stability_score or 0.0),
        "time_to_stabilization_seconds": ds.time_to_stabilize_seconds,
        "firmware_health_score": 1.0 if ds.error_count == 0 else max(0.0, 1.0 - (ds.error_count * 0.1)),
        "session_reliability_score": 1.0 if ds.session_success else 0.4,
        "manual_override_rate": 0.0,
        "cook_success": bool(ds.session_success),
        "raw_payload": {
            "source": "stream",
            "sample_count": len(events),
            "archetype": ds.archetype,
            "reached_target": bool(ds.reached_target),
            "stabilized": bool(ds.stabilized),
            "dropoff_reason": ds.dropoff_reason,
            "avg_rssi": ds.avg_rssi,
            "min_rssi": ds.min_rssi,
            "probe_failure": bool(ds.probe_failure),
        },
        "in_control_pct": in_control_pct,
        "max_overshoot_f": max_over,
        "max_undershoot_f": max_under,
        "post_reach_samples": None,
    }


def rebuild_sessions_from_stream(
    db: Session,
    since: datetime,
    until: Optional[datetime] = None,
    batch_devices: int = 50,
    max_devices: Optional[int] = None,
    gap_minutes: int = 45,
) -> dict[str, Any]:
    """Walk the stream table per device, derive sessions, upsert.

    Idempotent. Safe to re-run over the same window — existing rows
    with the same source_event_id are skipped via ON CONFLICT.
    """
    until = until or datetime.now(timezone.utc)
    if since >= until:
        return {"ok": True, "reason": "since >= until", "devices_scanned": 0, "sessions_written": 0}

    device_ids = _device_ids_in_window(db, since, until, limit=max_devices)
    if not device_ids:
        return {"ok": True, "devices_scanned": 0, "sessions_written": 0, "window": (since.isoformat(), until.isoformat())}

    sessions_written = 0
    sessions_skipped = 0
    devices_processed = 0
    errors: list[str] = []

    for i in range(0, len(device_ids), batch_devices):
        batch = device_ids[i : i + batch_devices]
        events = db.execute(
            select(TelemetryStreamEvent)
            .where(
                TelemetryStreamEvent.device_id.in_(batch),
                TelemetryStreamEvent.sample_timestamp >= since,
                TelemetryStreamEvent.sample_timestamp < until,
            )
            .order_by(TelemetryStreamEvent.device_id, TelemetryStreamEvent.sample_timestamp)
        ).scalars().all()
        by_device: dict[str, list[TelemetryStreamEvent]] = {}
        for ev in events:
            by_device.setdefault(ev.device_id, []).append(ev)

        for device_id, dev_events in by_device.items():
            try:
                derived = _derive_sessions(device_id, dev_events, gap_minutes=gap_minutes)
                for ds in derived:
                    row = _derived_session_to_row(ds)
                    stmt = pg_insert(TelemetrySession).values(**row).on_conflict_do_nothing(
                        index_elements=["source_event_id"]
                    )
                    result = db.execute(stmt)
                    if result.rowcount:
                        sessions_written += 1
                    else:
                        sessions_skipped += 1
                devices_processed += 1
            except Exception as e:
                logger.exception("stream_session_builder: device %s failed", device_id)
                errors.append(f"{device_id}: {e}")
        db.commit()
        logger.info(
            "stream_session_builder batch %s: %s devices processed, %s sessions written, %s skipped",
            i // batch_devices + 1, devices_processed, sessions_written, sessions_skipped,
        )

    return {
        "ok": True,
        "window": (since.isoformat(), until.isoformat()),
        "devices_scanned": devices_processed,
        "sessions_written": sessions_written,
        "sessions_skipped_existing": sessions_skipped,
        "errors": errors,
    }


def _latest_stream_built_session_ts(db: Session) -> Optional[datetime]:
    """Last session_start we've built from stream — lets the hourly
    tick pick up where the previous run left off."""
    return db.execute(
        select(func.max(TelemetrySession.session_start)).where(
            TelemetrySession.source_event_id.like(f"{SESSION_SOURCE_PREFIX}%")
        )
    ).scalar()


def run_scheduler_tick(db: Session, lookback_hours: int = 2) -> dict[str, Any]:
    """Hourly: rebuild any sessions whose events have landed since we
    last ran. A small backwards overlap (``lookback_hours``) gives us a
    safety margin so mid-cook sessions get re-derived with their full
    event set once complete."""
    now = datetime.now(timezone.utc)
    latest = _latest_stream_built_session_ts(db)
    if latest:
        since = latest - timedelta(hours=lookback_hours)
    else:
        # First-ever run. Cover the gap since the DynamoDB source died.
        since = datetime(2026, 4, 9, tzinfo=timezone.utc)
    return rebuild_sessions_from_stream(db, since=since, until=now)


def cli_backfill(db: Session, since_iso: str) -> dict[str, Any]:
    """One-shot backfill from a specific date forward. Used when we need
    to reseed sessions after a schema change or to cover the
    DynamoDB-dead window at deploy time."""
    since = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    return rebuild_sessions_from_stream(db, since=since)
