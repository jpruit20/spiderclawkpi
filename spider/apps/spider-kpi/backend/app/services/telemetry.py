from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import desc, inspect, select
from sqlalchemy.orm import Session

from app.models import SourceSyncRun, TelemetryDaily, TelemetrySession


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _severity_from_rate(rate: float, high: float, medium: float) -> str:
    if rate >= high:
        return "high"
    if rate >= medium:
        return "medium"
    return "low"


def telemetry_tables_available(db: Session) -> bool:
    inspector = inspect(db.bind)
    return inspector.has_table('telemetry_daily') and inspector.has_table('telemetry_sessions')


def summarize_telemetry(db: Session, lookback_days: int = 30) -> dict[str, Any]:
    if not telemetry_tables_available(db):
        return {
            "latest": None,
            "daily": [],
            "firmware_health": [],
            "grill_type_health": [],
            "top_error_codes": [],
            "top_issue_patterns": [],
        }

    rows = db.execute(
        select(TelemetryDaily)
        .order_by(desc(TelemetryDaily.business_date))
        .limit(max(lookback_days, 1))
    ).scalars().all()
    if not rows:
        return {
            "latest": None,
            "daily": [],
            "firmware_health": [],
            "grill_type_health": [],
            "top_error_codes": [],
            "top_issue_patterns": [],
        }

    latest = rows[0]
    sessions = db.execute(
        select(TelemetrySession)
        .where(TelemetrySession.session_start >= datetime.now(timezone.utc) - timedelta(days=lookback_days))
        .order_by(desc(TelemetrySession.session_start))
        .limit(5000)
    ).scalars().all()

    firmware = defaultdict(lambda: {"sessions": 0, "disconnects": 0, "overrides": 0, "failures": 0})
    grill_types = defaultdict(lambda: {"sessions": 0, "disconnects": 0, "overrides": 0, "failures": 0})
    error_codes: Counter[str] = Counter()
    issue_patterns: Counter[str] = Counter()

    for item in sessions:
        fw = item.firmware_version or "unknown"
        gt = item.grill_type or "unknown"
        firmware[fw]["sessions"] += 1
        grill_types[gt]["sessions"] += 1
        firmware[fw]["disconnects"] += item.disconnect_events or 0
        grill_types[gt]["disconnects"] += item.disconnect_events or 0
        firmware[fw]["overrides"] += item.manual_overrides or 0
        grill_types[gt]["overrides"] += item.manual_overrides or 0
        if not item.cook_success:
            firmware[fw]["failures"] += 1
            grill_types[gt]["failures"] += 1
        for code in item.error_codes_json or []:
            error_codes[str(code)] += 1
        if (item.disconnect_events or 0) > 0:
            issue_patterns["disconnect_cluster"] += 1
        if (item.temp_stability_score or 1.0) < 0.75:
            issue_patterns["temp_instability"] += 1
        if (item.manual_override_rate or 0.0) >= 0.2:
            issue_patterns["high_manual_override"] += 1
        if (item.firmware_health_score or 1.0) < 0.8:
            issue_patterns["firmware_health_drop"] += 1

    def _health_payload(rows_map: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
        payload = []
        for key, values in rows_map.items():
            total = values["sessions"]
            disconnect_rate = _safe_div(values["disconnects"], total)
            override_rate = _safe_div(values["overrides"], total)
            failure_rate = _safe_div(values["failures"], total)
            health_score = round(max(0.0, 1.0 - (disconnect_rate * 0.35 + override_rate * 0.2 + failure_rate * 0.45)), 3)
            payload.append({
                "key": key,
                "sessions": total,
                "disconnect_rate": round(disconnect_rate, 3),
                "manual_override_rate": round(override_rate, 3),
                "failure_rate": round(failure_rate, 3),
                "health_score": health_score,
                "severity": _severity_from_rate(1.0 - health_score, 0.35, 0.18),
            })
        return sorted(payload, key=lambda item: (item["severity"] == "high", item["health_score"], -item["sessions"]), reverse=True)

    latest_run = db.execute(
        select(SourceSyncRun)
        .where(SourceSyncRun.source_name == 'aws_telemetry', SourceSyncRun.status == 'success')
        .order_by(desc(SourceSyncRun.started_at))
        .limit(1)
    ).scalars().first()
    metadata = latest_run.metadata_json if latest_run else {}
    max_record_cap_hit = bool(metadata.get('max_record_cap_hit'))
    scan_truncated = bool(metadata.get('scan_truncated'))
    distinct_devices = metadata.get('distinct_devices_observed') or 0
    distinct_engaged_devices = metadata.get('distinct_engaged_devices_observed') or 0
    confidence = {
        "global_completeness": "proxy" if (max_record_cap_hit or scan_truncated or distinct_devices <= 1) else "estimated",
        "session_derivation": "estimated",
        "disconnect_detection": "proxy",
        "cook_success": "estimated",
        "manual_override": "unavailable" if all((item.manual_overrides or 0) == 0 for item in sessions) else "proxy",
        "reason": metadata.get('coverage_summary') or "Direct DynamoDB reads from sg_device_shadows are bounded and device-keyed; fleet-wide recency is not globally indexed.",
    }

    return {
        "latest": {
            "business_date": latest.business_date,
            "sessions": latest.sessions,
            "connected_users": latest.connected_users,
            "cook_success_rate": latest.cook_success_rate,
            "disconnect_rate": latest.disconnect_rate,
            "temp_stability_score": latest.temp_stability_score,
            "avg_time_to_stabilization_seconds": latest.avg_time_to_stabilization_seconds,
            "manual_override_rate": latest.manual_override_rate,
            "firmware_health_score": latest.firmware_health_score,
            "session_reliability_score": latest.session_reliability_score,
            "error_rate": latest.error_rate,
        },
        "daily": [
            {
                "business_date": row.business_date,
                "sessions": row.sessions,
                "connected_users": row.connected_users,
                "cook_success_rate": row.cook_success_rate,
                "disconnect_rate": row.disconnect_rate,
                "temp_stability_score": row.temp_stability_score,
                "avg_time_to_stabilization_seconds": row.avg_time_to_stabilization_seconds,
                "manual_override_rate": row.manual_override_rate,
                "firmware_health_score": row.firmware_health_score,
                "session_reliability_score": row.session_reliability_score,
                "error_rate": row.error_rate,
            }
            for row in reversed(rows)
        ],
        "firmware_health": _health_payload(firmware)[:10],
        "grill_type_health": _health_payload(grill_types)[:10],
        "top_error_codes": [{"code": code, "count": count} for code, count in error_codes.most_common(10)],
        "top_issue_patterns": [{"pattern": key, "count": count} for key, count in issue_patterns.most_common(10)],
        "collection_metadata": {
            "source": "sg_device_shadows",
            "region": metadata.get('region'),
            "table": metadata.get('table'),
            "sample_source": metadata.get('sample_source'),
            "records_loaded": metadata.get('records_loaded'),
            "sessions_derived": metadata.get('sessions_derived'),
            "days_materialized": metadata.get('days_materialized'),
            "max_records": metadata.get('max_records'),
            "devices_observed": metadata.get('devices_observed'),
            "distinct_devices_observed": metadata.get('distinct_devices_observed'),
            "distinct_engaged_devices_observed": metadata.get('distinct_engaged_devices_observed'),
            "oldest_sample_timestamp_seen": metadata.get('oldest_sample_timestamp_seen'),
            "newest_sample_timestamp_seen": metadata.get('newest_sample_timestamp_seen'),
            "samples_retained": metadata.get('samples_retained'),
            "excluded_records": metadata.get('excluded_records'),
            "excluded_breakdown": metadata.get('excluded_breakdown'),
            "invalid_records": metadata.get('invalid_records'),
            "duplicate_samples": metadata.get('duplicate_samples'),
            "sessions_merged_away": metadata.get('sessions_merged_away'),
            "short_sessions_filtered": metadata.get('short_sessions_filtered'),
            "pages_scanned": metadata.get('pages_scanned'),
            "scan_truncated": metadata.get('scan_truncated'),
            "raw_rows_scanned": metadata.get('raw_rows_scanned'),
            "recent_rows_after_cutoff": metadata.get('recent_rows_after_cutoff'),
            "max_record_cap_hit": metadata.get('max_record_cap_hit'),
            "session_gap_timeout_minutes": metadata.get('session_gap_timeout_minutes'),
            "coverage_summary": metadata.get('coverage_summary'),
        },
        "confidence": confidence,
    }
