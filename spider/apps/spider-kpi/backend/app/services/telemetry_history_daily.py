from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TelemetryHistoryDaily


def get_telemetry_history_daily(db: Session, limit: int = 900) -> list[dict[str, Any]]:
    # Filter to only return rows within the limit (days)
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
            'source': row.source,
        }
        for row in rows
    ]
