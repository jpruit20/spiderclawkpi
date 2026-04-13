from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TelemetryHistoryDaily


def get_telemetry_history_daily(db: Session, limit: int = 900) -> list[dict[str, Any]]:
    cutoff_date = datetime.now(timezone.utc).date() - timedelta(days=limit)
    rows = db.execute(
        select(TelemetryHistoryDaily)
        .where(TelemetryHistoryDaily.business_date >= cutoff_date)
        .order_by(TelemetryHistoryDaily.business_date)
    ).scalars().all()
    return [
        {
            'business_date': row.business_date.isoformat(),
            'active_devices': row.active_devices,
            'engaged_devices': row.engaged_devices,
            'total_events': row.total_events,
            'avg_rssi': row.avg_rssi,
            'error_events': row.error_events,
            'firmware_distribution': row.firmware_distribution or {},
            'model_distribution': row.model_distribution or {},
            'avg_cook_temp': row.avg_cook_temp,
            'peak_hour_distribution': row.peak_hour_distribution or {},
            'session_count': row.session_count,
            'successful_sessions': row.successful_sessions,
            'cook_styles_json': row.cook_styles_json or {},
            'cook_style_details_json': row.cook_style_details_json or {},
            'temp_range_json': row.temp_range_json or {},
            'duration_range_json': row.duration_range_json or {},
            'unique_devices_seen': row.unique_devices_seen,
            'source': row.source,
        }
        for row in rows
    ]


def get_cook_analysis_for_range(
    db: Session,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """Aggregate pre-materialized cook analysis across a date range."""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    rows = db.execute(
        select(TelemetryHistoryDaily)
        .where(
            TelemetryHistoryDaily.business_date >= start,
            TelemetryHistoryDaily.business_date <= end,
        )
        .order_by(TelemetryHistoryDaily.business_date)
    ).scalars().all()

    # Aggregate across all days
    total_sessions = 0
    total_successful = 0
    cook_styles: dict[str, int] = defaultdict(int)
    temp_ranges: dict[str, int] = defaultdict(int)
    duration_ranges: dict[str, int] = defaultdict(int)
    # For weighted averages per style
    style_counts: dict[str, int] = defaultdict(int)
    style_dur_sum: dict[str, float] = defaultdict(float)
    style_stability_sum: dict[str, float] = defaultdict(float)
    style_stability_n: dict[str, int] = defaultdict(int)
    style_success_sum: dict[str, float] = defaultdict(float)
    style_success_n: dict[str, int] = defaultdict(int)
    # Monthly breakdown
    monthly: dict[str, dict[str, int]] = defaultdict(lambda: {"sessions": 0, "active_devices": 0})
    # Fleet metrics
    days_with_data = 0
    total_unique_devices_sum = 0
    all_active_sum = 0

    for row in rows:
        sc = row.session_count or 0
        total_sessions += sc
        total_successful += row.successful_sessions or 0

        styles = row.cook_styles_json or {}
        for k, v in styles.items():
            cook_styles[k] += v

        for k, v in (row.temp_range_json or {}).items():
            temp_ranges[k] += v
        for k, v in (row.duration_range_json or {}).items():
            duration_ranges[k] += v

        details = row.cook_style_details_json or {}
        for style_name, d in details.items():
            c = d.get("count", 0)
            if c == 0:
                continue
            style_counts[style_name] += c
            style_dur_sum[style_name] += d.get("avg_duration_seconds", 0) * c
            stab = d.get("avg_stability_score")
            if stab is not None:
                style_stability_sum[style_name] += stab * c
                style_stability_n[style_name] += c
            sr = d.get("success_rate")
            if sr is not None:
                style_success_sum[style_name] += sr * c
                style_success_n[style_name] += c

        # Monthly
        month_key = row.business_date.strftime("%Y-%m")
        monthly[month_key]["sessions"] += sc
        monthly[month_key]["active_devices"] += row.active_devices or 0

        if sc > 0:
            days_with_data += 1
        total_unique_devices_sum += row.unique_devices_seen or row.active_devices or 0
        all_active_sum += row.active_devices or 0

    # Build aggregated style details
    style_details: dict[str, dict[str, Any]] = {}
    for name, count in cook_styles.items():
        if count == 0:
            continue
        sc_n = style_counts.get(name, count)
        style_details[name] = {
            "count": count,
            "pct": round(count / max(total_sessions, 1), 4),
            "avg_duration_seconds": round(style_dur_sum.get(name, 0) / max(sc_n, 1)),
            "avg_stability_score": round(style_stability_sum.get(name, 0) / max(style_stability_n.get(name, 1), 1), 3) if style_stability_n.get(name) else None,
            "success_rate": round(style_success_sum.get(name, 0) / max(style_success_n.get(name, 1), 1), 4) if style_success_n.get(name) else None,
        }

    monthly_breakdown = sorted(
        [{"month": k, "sessions": v["sessions"], "active_devices": v["active_devices"]} for k, v in monthly.items()],
        key=lambda x: x["month"],
    )

    return {
        "total_sessions": total_sessions,
        "successful_sessions": total_successful,
        "cook_styles": dict(cook_styles),
        "style_details": style_details,
        "temp_ranges": dict(temp_ranges),
        "duration_ranges": dict(duration_ranges),
        "monthly_breakdown": monthly_breakdown,
        "fleet_total_unique_devices": total_unique_devices_sum,
        "date_range": {
            "start": start_date,
            "end": end_date,
            "days_with_data": days_with_data,
            "total_days": len(rows),
        },
    }
