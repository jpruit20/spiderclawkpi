from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib import request as urllib_request

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


def epoch_ms_to_iso(value: Any) -> str | None:
    try:
        raw = int(value)
    except (TypeError, ValueError):
        return None
    if raw <= 0:
        return None
    if raw > 10_000_000_000:
        dt = datetime.fromtimestamp(raw / 1000, tz=timezone.utc)
    else:
        dt = datetime.fromtimestamp(raw, tz=timezone.utc)
    return dt.isoformat()


def normalize_stream_record(record: dict[str, Any]) -> dict[str, Any] | None:
    dynamodb = record.get('dynamodb') or {}
    new_image = dynamodb.get('NewImage') or {}
    item = deserialize_item(new_image)
    device_id = item.get('device_id')
    sample_time = item.get('sample_time')
    if not device_id or sample_time is None:
        return None
    sample_iso = epoch_ms_to_iso(sample_time)
    reported = ((item.get('device_data') or {}).get('reported') or {}) if isinstance(item.get('device_data'), dict) else {}
    heat_t2 = ((reported.get('heat') or {}).get('t2') or {}) if isinstance(reported.get('heat'), dict) else {}
    source_event_id = f"{device_id}:{sample_time}"
    return {
        'source_event_id': source_event_id,
        'device_id': str(device_id),
        'sample_timestamp': sample_iso,
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


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    api_base = os.environ['KPI_API_BASE_URL'].rstrip('/')
    api_password = os.environ['KPI_API_PASSWORD']

    normalized = []
    for record in event.get('Records', []):
        if record.get('eventSource') != 'aws:dynamodb':
            continue
        payload = normalize_stream_record(record)
        if payload:
            normalized.append(payload)

    body = json.dumps({'records': normalized}).encode('utf-8')
    req = urllib_request.Request(
        api_base + '/api/admin/ingest/telemetry-stream',
        data=body,
        method='POST',
        headers={
            'Content-Type': 'application/json',
            'X-App-Password': api_password,
        },
    )
    with urllib_request.urlopen(req, timeout=20) as resp:
        response_body = resp.read().decode('utf-8')
    parsed = json.loads(response_body)
    return {
        'records_received': len(event.get('Records', [])),
        'records_normalized': len(normalized),
        **parsed,
    }
