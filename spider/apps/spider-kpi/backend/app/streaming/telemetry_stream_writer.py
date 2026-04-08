from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.entities import TelemetryStreamEvent


DYNAMODB_TYPES = {'S', 'N', 'BOOL', 'NULL', 'M', 'L'}


def deserialize_attribute(value: Any) -> Any:
    if not isinstance(value, dict) or len(value) != 1:
        return value
    key, payload = next(iter(value.items()))
    if key == 'S':
        return payload
    if key == 'N':
        return float(payload) if '.' in str(payload) else int(payload)
    if key == 'BOOL':
        return bool(payload)
    if key == 'NULL':
        return None
    if key == 'M':
        return {inner_key: deserialize_attribute(inner_value) for inner_key, inner_value in payload.items()}
    if key == 'L':
        return [deserialize_attribute(item) for item in payload]
    return payload


def deserialize_item(item: dict[str, Any]) -> dict[str, Any]:
    if all(isinstance(value, dict) and len(value) == 1 and next(iter(value.keys())) in DYNAMODB_TYPES for value in item.values()):
        return {key: deserialize_attribute(value) for key, value in item.items()}
    return item


def epoch_ms_to_dt(value: Any) -> datetime | None:
    try:
        raw = int(value)
    except (TypeError, ValueError):
        return None
    if raw <= 0:
        return None
    if raw > 10_000_000_000:
        return datetime.fromtimestamp(raw / 1000, tz=timezone.utc)
    return datetime.fromtimestamp(raw, tz=timezone.utc)


def normalize_stream_record(record: dict[str, Any]) -> dict[str, Any] | None:
    dynamodb = record.get('dynamodb') or {}
    new_image = dynamodb.get('NewImage') or {}
    item = deserialize_item(new_image)
    device_id = item.get('device_id')
    sample_time = item.get('sample_time')
    if not device_id or sample_time is None:
        return None
    sample_dt = epoch_ms_to_dt(sample_time)
    reported = ((item.get('device_data') or {}).get('reported') or {}) if isinstance(item.get('device_data'), dict) else {}
    heat_t2 = ((reported.get('heat') or {}).get('t2') or {}) if isinstance(reported.get('heat'), dict) else {}
    source_event_id = f"{device_id}:{sample_time}"
    return {
        'source_event_id': source_event_id,
        'device_id': str(device_id),
        'sample_timestamp': sample_dt,
        'stream_event_name': record.get('eventName'),
        'engaged': bool(reported.get('engaged', False)),
        'firmware_version': reported.get('vers'),
        'grill_type': reported.get('model'),
        'target_temp': float(heat_t2.get('trgt')) if heat_t2.get('trgt') is not None else None,
        'current_temp': float(reported.get('mainTemp')) if reported.get('mainTemp') is not None else None,
        'heating': bool(heat_t2.get('heating', False)),
        'intensity': float(heat_t2.get('intensity')) if heat_t2.get('intensity') is not None else None,
        'rssi': float(reported.get('RSSI')) if reported.get('RSSI') is not None else None,
        'error_codes_json': [int(code) for code in (reported.get('errors') or [])],
        'raw_payload': item,
    }


def write_stream_records(db: Session, normalized_records: list[dict[str, Any]]) -> dict[str, Any]:
    inserted = 0
    skipped = 0
    for payload in normalized_records:
        stmt = insert(TelemetryStreamEvent).values(**payload)
        stmt = stmt.on_conflict_do_nothing(index_elements=['source_event_id'])
        result = db.execute(stmt)
        inserted += int(result.rowcount or 0)
        if not (result.rowcount or 0):
            skipped += 1
    db.commit()
    return {'inserted': inserted, 'skipped': skipped}
