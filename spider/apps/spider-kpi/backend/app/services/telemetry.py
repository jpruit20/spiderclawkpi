from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import desc, inspect, select
from sqlalchemy.orm import Session

from app.models import TelemetryDaily, TelemetrySession


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
    }
