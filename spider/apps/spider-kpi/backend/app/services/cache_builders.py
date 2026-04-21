"""Registered cache builders — one function per cache_key.

Import this module once at app startup to register every builder. The
scheduler's rebuild-all job then covers them automatically. Endpoints
read by the matching key.

Adding a new cached endpoint:
    1. Write a pure function (db) -> JSON-safe dict
    2. Register it here with a stable cache_key and source_version
    3. Update the endpoint to read cache-first via aggregate_cache.get
       (or build_if_missing for lazy first-populate)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import Session

from app.models import TelemetrySession, TelemetryStreamEvent
from app.services import aggregate_cache
from app.services.cx_snapshot import build_customer_experience_snapshot
from app.services.product_taxonomy import classify_product


# ── cx_snapshot — full Customer Experience snapshot payload ────────────

CX_SNAPSHOT_KEY = "cx:snapshot:v1"


def _build_cx_snapshot(db: Session) -> dict[str, Any]:
    return build_customer_experience_snapshot(db)


# ── firmware_metrics_7d — the default Product Engineering view ─────────

FIRMWARE_METRICS_7D_KEY = "firmware:metrics:window:7d"


def _build_firmware_metrics_7d(db: Session) -> dict[str, Any]:
    """Default 7-day window over the live stream + session tables.

    Same logic as the /api/firmware/overview/metrics endpoint but with
    no parameters (we precompute only the default view; custom ranges
    still hit live compute with the in-memory TTL cache fallback). The
    Product Engineering page uses the 7-day default 99% of the time, so
    caching just that window captures nearly all the load.
    """
    now = datetime.now(timezone.utc)
    end_dt = now
    start_dt = end_dt - timedelta(days=7)

    agg_row = db.execute(
        select(
            func.count(TelemetrySession.id).label("sessions"),
            func.sum(case((TelemetrySession.cook_success.is_(True), 1), else_=0)).label("successes"),
            func.avg(TelemetrySession.in_control_pct).label("avg_in_control"),
            func.sum(TelemetrySession.disconnect_events).label("disconnect_events"),
            func.count(func.distinct(TelemetrySession.device_id)).label("devices"),
        ).where(
            TelemetrySession.session_start >= start_dt,
            TelemetrySession.session_start < end_dt,
        )
    ).one()
    sessions = int(agg_row.sessions or 0)
    successes = int(agg_row.successes or 0)
    avg_in_control = float(agg_row.avg_in_control) if agg_row.avg_in_control is not None else None
    disconnect_events = int(agg_row.disconnect_events or 0)
    devices = int(agg_row.devices or 0)
    success_rate = (successes / sessions) if sessions else None
    disconnect_rate_per_session = (disconnect_events / sessions) if sessions else None

    latest_session_ts = db.execute(select(func.max(TelemetrySession.session_start))).scalar()
    sessions_stale = sessions == 0 and latest_session_ts is not None and latest_session_ts < start_dt

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
        "firmware_version": None,
        "sessions": sessions,
        "sessions_source": "telemetry_sessions",
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


# ── Registration — called once at app startup via import ───────────────

def register_all() -> None:
    aggregate_cache.register(CX_SNAPSHOT_KEY, _build_cx_snapshot, source_version="v1")
    aggregate_cache.register(FIRMWARE_METRICS_7D_KEY, _build_firmware_metrics_7d, source_version="v1")


# Register at import so any module that imports this file wires up the
# builders exactly once. Safe on hot reload (register() is idempotent).
register_all()
