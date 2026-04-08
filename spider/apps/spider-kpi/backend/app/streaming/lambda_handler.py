from __future__ import annotations

from typing import Any

from app.db.session import SessionLocal
from app.streaming.telemetry_stream_writer import normalize_stream_record, write_stream_records


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    normalized = []
    for record in event.get('Records', []):
        if record.get('eventSource') != 'aws:dynamodb':
            continue
        payload = normalize_stream_record(record)
        if payload:
            normalized.append(payload)

    db = SessionLocal()
    try:
        write_result = write_stream_records(db, normalized)
    finally:
        db.close()

    return {
        'records_received': len(event.get('Records', [])),
        'records_normalized': len(normalized),
        **write_result,
    }
