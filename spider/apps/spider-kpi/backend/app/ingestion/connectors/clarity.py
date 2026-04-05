from __future__ import annotations

from typing import Any

import requests
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.source_health import finish_sync_run, start_sync_run, upsert_source_config

settings = get_settings()
TIMEOUT_SECONDS = 45


def sync_clarity(db: Session, days: int = 3) -> dict[str, Any]:
    configured = bool(settings.clarity_project_id and settings.clarity_api_token and settings.clarity_base_url)
    upsert_source_config(
        db,
        'clarity',
        configured=configured,
        sync_mode='poll',
        config_json={'project_id': settings.clarity_project_id, 'source_type': 'connector'},
    )
    db.commit()

    if not configured:
        return {'ok': False, 'message': 'Clarity not fully configured (project_id/api_token/base_url required)', 'records_processed': 0}

    run = start_sync_run(db, 'clarity', 'data_export', {'days': days})
    db.commit()

    try:
        url = f"{settings.clarity_base_url.rstrip('/')}/projects/{settings.clarity_project_id}/export-data?numOfDays={days}"
        response = requests.get(
            url,
            headers={'Authorization': f'Bearer {settings.clarity_api_token}', 'Accept': 'application/json'},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
        records = body.get('records') or body.get('rows') or []
        run.metadata_json = {
            **(run.metadata_json or {}),
            'project_id': settings.clarity_project_id,
            'sample': records[:3] if isinstance(records, list) else body,
        }
        finish_sync_run(db, run, status='success', records_processed=len(records) if isinstance(records, list) else 1)
        db.commit()
        return {'ok': True, 'records_processed': len(records) if isinstance(records, list) else 1, 'project_id': settings.clarity_project_id}
    except Exception as exc:
        finish_sync_run(db, run, status='failed', error_message=str(exc))
        db.commit()
        return {'ok': False, 'message': str(exc), 'records_processed': 0}
