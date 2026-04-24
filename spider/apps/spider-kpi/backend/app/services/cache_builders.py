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

from sqlalchemy import case, desc, func, select, text
from sqlalchemy.orm import Session

from app.models import TelemetrySession, TelemetryStreamEvent
from app.services import aggregate_cache
from app.services.cx_snapshot import build_customer_experience_snapshot
from app.services.product_taxonomy import (
    build_huntsman_device_ids,
    build_t2_max_by_device,
    build_test_cohort_device_ids,
    classify_product,
)


# ── cx_snapshot — full Customer Experience snapshot payload ────────────

CX_SNAPSHOT_KEY = "cx:snapshot:v1"


def _build_cx_snapshot(db: Session) -> dict[str, Any]:
    """Round-trip through CXSnapshotOut so ORM objects inside ``actions``
    / ``today_focus`` get serialized to plain dicts before they hit the
    JSONB store. Without this step, json.dumps(default=str) stringifies
    the ORM instances to garbage like "<CXAction object at 0x...>" and
    breaks response-model validation on reads."""
    from app.schemas.overview import CXSnapshotOut
    raw = build_customer_experience_snapshot(db)
    return CXSnapshotOut.model_validate(raw).model_dump(mode="json")


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

    # Canonical per-device classification for product distribution —
    # see firmware.py::overview_metrics for the rationale. The grouped
    # query above can't feed the history-aware classifier because it
    # loses device identity. Fleet Health excludes alpha/beta testers
    # (they skew firmware_distribution and product_distribution with
    # experimental builds); the Firmware Hub endpoint includes them
    # via its own include_testers=True path.
    per_device_rows = db.execute(text("""
        SELECT DISTINCT ON (device_id)
            device_id, grill_type, firmware_version
        FROM telemetry_stream_events
        WHERE sample_timestamp >= :start_dt
          AND sample_timestamp < :end_dt
          AND device_id IS NOT NULL
          AND device_id NOT LIKE 'mac:%%'
        ORDER BY device_id, sample_timestamp DESC
    """), {"start_dt": start_dt, "end_dt": end_dt}).all()
    huntsman_ids = build_huntsman_device_ids(db)
    t2_max_map = build_t2_max_by_device(db)
    test_ids = build_test_cohort_device_ids(db)
    product_counts: dict[str, int] = {}
    firmware_counts: dict[str | None, int] = {}
    test_cohort_count = 0
    for device_id, grill_type_val, fw_val in per_device_rows:
        if device_id in test_ids:
            test_cohort_count += 1
            continue
        family = classify_product(
            grill_type_val, fw_val,
            device_id=device_id,
            huntsman_device_ids=huntsman_ids,
            t2_max=t2_max_map.get(device_id),
        )
        product_counts[family] = product_counts.get(family, 0) + 1
        firmware_counts[fw_val] = firmware_counts.get(fw_val, 0) + 1

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
        "test_cohort_excluded": test_cohort_count,
        "include_testers": False,
    }


# ── overview — Command Center's base payload ───────────────────────────

OVERVIEW_KEY = "overview:base:v1"


def _build_overview(db: Session) -> dict[str, Any]:
    """Full /api/overview payload. Was 10.5s on the live droplet because
    it rolls up alerts, diagnostics, recommendations, source health,
    and a telemetry summary in a single shot. Round-trip through the
    OverviewResponse schema so any ORM objects inside (Alert, Diagnostic,
    Recommendation, SourceHealth) serialize to plain dicts before hitting
    JSONB — otherwise json.dumps(default=str) stringifies them to
    garbage and response validation fails on reads."""
    from app.services.overview import build_overview
    from app.schemas.overview import OverviewResponse
    raw = build_overview(db)
    return OverviewResponse.model_validate(raw).model_dump(mode="json")


# ── firmware_overview — Firmware Hub landing card ──────────────────────

FIRMWARE_OVERVIEW_KEY = "firmware:overview:v1"


def _build_firmware_overview(db: Session) -> dict[str, Any]:
    """Firmware Hub's first card — active devices, firmware distribution,
    and flagged versions. Lives next to firmware_metrics so caching them
    together keeps the Firmware Hub page snappy."""
    from app.api.routes.firmware import _build_firmware_overview_payload
    return _build_firmware_overview_payload(db)


# ── telemetry_summary_30d — Product Engineering default view ───────────

TELEMETRY_SUMMARY_30D_KEY = "telemetry:summary:window:30d"


def _build_telemetry_summary_30d(db: Session) -> dict[str, Any]:
    """Default 30-day telemetry summary. The Product Engineering page
    hits this on load; custom date ranges from the date picker skip the
    cache and hit live compute."""
    from app.services.telemetry import summarize_telemetry
    from app.services.telemetry_history_daily import get_telemetry_history_daily
    payload = summarize_telemetry(db, lookback_days=30)
    payload["history_daily"] = get_telemetry_history_daily(db, limit=30)
    return payload


# ── Registration — called once at app startup via import ───────────────

def register_all() -> None:
    aggregate_cache.register(CX_SNAPSHOT_KEY, _build_cx_snapshot, source_version="v1")
    aggregate_cache.register(FIRMWARE_METRICS_7D_KEY, _build_firmware_metrics_7d, source_version="v1")
    aggregate_cache.register(OVERVIEW_KEY, _build_overview, source_version="v1")
    aggregate_cache.register(FIRMWARE_OVERVIEW_KEY, _build_firmware_overview, source_version="v1")
    aggregate_cache.register(TELEMETRY_SUMMARY_30D_KEY, _build_telemetry_summary_30d, source_version="v1")


# Register at import so any module that imports this file wires up the
# builders exactly once. Safe on hot reload (register() is idempotent).
register_all()
