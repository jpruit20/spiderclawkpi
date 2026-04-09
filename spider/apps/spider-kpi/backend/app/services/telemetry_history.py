from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TelemetryHistoryMonthly


def upsert_telemetry_history_monthly(
    db: Session,
    *,
    monthly_rows: list[dict[str, Any]],
    window_days: int,
    distinct_devices: int,
    distinct_engaged_devices: int,
    observed_mac_count: int,
    source: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    inserted = 0
    updated = 0
    metadata = metadata or {}
    now = datetime.now(timezone.utc)

    for row in monthly_rows:
        month_start = row.get('month_start')
        if isinstance(month_start, str):
            month_start = date.fromisoformat(month_start)
        if not isinstance(month_start, date):
            continue
        existing = db.execute(
            select(TelemetryHistoryMonthly).where(TelemetryHistoryMonthly.month_start == month_start)
        ).scalar_one_or_none()
        payload = {
            'distinct_devices': max(0, int(row.get('distinct_devices') or 0)),
            'distinct_engaged_devices': max(0, int(row.get('distinct_engaged_devices') or 0)),
            'observed_mac_count': observed_mac_count,
            'source': source,
            'coverage_window_days': window_days,
            'metadata_json': {
                **metadata,
                'global_distinct_devices': distinct_devices,
                'global_distinct_engaged_devices': distinct_engaged_devices,
                'observed_mac_count': observed_mac_count,
                'ingested_at': now.isoformat(),
            },
        }
        if existing is None:
            db.add(TelemetryHistoryMonthly(month_start=month_start, **payload))
            inserted += 1
        else:
            existing.distinct_devices = payload['distinct_devices']
            existing.distinct_engaged_devices = payload['distinct_engaged_devices']
            existing.observed_mac_count = payload['observed_mac_count']
            existing.source = payload['source']
            existing.coverage_window_days = payload['coverage_window_days']
            existing.metadata_json = payload['metadata_json']
            updated += 1
    db.flush()
    return {
        'ok': True,
        'inserted': inserted,
        'updated': updated,
        'months_loaded': inserted + updated,
        'window_days': window_days,
        'distinct_devices': distinct_devices,
        'distinct_engaged_devices': distinct_engaged_devices,
        'observed_mac_count': observed_mac_count,
    }


def get_telemetry_history_monthly(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        select(TelemetryHistoryMonthly).order_by(TelemetryHistoryMonthly.month_start)
    ).scalars().all()
    return [
        {
            'month_start': row.month_start.isoformat(),
            'distinct_devices': row.distinct_devices,
            'distinct_engaged_devices': row.distinct_engaged_devices,
            'observed_mac_count': row.observed_mac_count,
            'source': row.source,
            'coverage_window_days': row.coverage_window_days,
        }
        for row in rows
    ]
