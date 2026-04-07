from __future__ import annotations

from typing import Any

import requests
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.source_health import finish_sync_run, start_sync_run, upsert_source_config

settings = get_settings()
TIMEOUT_SECONDS = 45


def _clarity_url() -> str:
    explicit = (settings.clarity_endpoint or '').strip()
    if explicit:
        if explicit.startswith('http://') or explicit.startswith('https://'):
            return explicit.rstrip('/')
        return f"https://{explicit.lstrip('/')}".rstrip('/')

    base = settings.clarity_base_url.rstrip('/')
    if base.endswith('/project-live-insights'):
        return base
    if base.endswith('/api/v1'):
        return f'{base}/project-live-insights'
    return base


def _extract_clarity_records(body: Any) -> list[Any]:
    if isinstance(body, list):
        rows: list[Any] = []
        for item in body:
            if isinstance(item, dict):
                info = item.get('information')
                if isinstance(info, list):
                    rows.extend(info)
                else:
                    rows.append(item)
        return rows

    if isinstance(body, dict):
        records = body.get('records') or body.get('rows') or body.get('information') or []
        return records if isinstance(records, list) else [records]

    return []


def sync_clarity(db: Session, days: int = 3) -> dict[str, Any]:
    configured = bool(settings.clarity_api_token and settings.clarity_base_url)
    upsert_source_config(
        db,
        'clarity',
        configured=configured,
        sync_mode='poll',
        config_json={'project_id': settings.clarity_project_id, 'source_type': 'connector'},
    )
    db.commit()

    if not configured:
        return {'ok': False, 'message': 'Clarity not fully configured (api_token/base_url required)', 'records_processed': 0}

    run = start_sync_run(db, 'clarity', 'data_export', {'days': days})
    db.commit()

    try:
        url = _clarity_url()
        response = requests.get(
            url,
            params={'numOfDays': max(1, min(days, 3)), 'dimension1': 'URL'},
            headers={'Authorization': f'Bearer {settings.clarity_api_token}', 'Accept': 'application/json'},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
        records = _extract_clarity_records(body)
        run.metadata_json = {
            **(run.metadata_json or {}),
            'project_id': settings.clarity_project_id,
            'request_url': response.url,
            'sample': records[:3] if records else body,
        }
        finish_sync_run(db, run, status='success', records_processed=len(records))
        db.commit()
        return {'ok': True, 'records_processed': len(records), 'project_id': settings.clarity_project_id}
    except Exception as exc:
        message = str(exc)
        retry_after = None
        if hasattr(exc, 'response') and getattr(exc, 'response', None) is not None:
            retry_after = exc.response.headers.get('Retry-After')
        if '429' in message and retry_after:
            message = f'{message} | Retry-After: {retry_after}'
        finish_sync_run(db, run, status='failed', error_message=message)
        db.commit()
        return {'ok': False, 'message': message, 'records_processed': 0}
