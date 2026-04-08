from __future__ import annotations

import os
from typing import Any

from app.db.session import SessionLocal, reset_engine
from app.streaming.telemetry_stream_writer import normalize_stream_record, write_stream_records


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    database_url = os.getenv('KPI_DATABASE_URL')
    if database_url:
        reset_engine(database_url)

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
