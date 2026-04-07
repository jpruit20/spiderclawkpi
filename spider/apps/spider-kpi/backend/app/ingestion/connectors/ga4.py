from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

import jwt
import requests
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.source_health import finish_sync_run, start_sync_run, upsert_source_config

settings = get_settings()
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GA4_SCOPE = 'https://www.googleapis.com/auth/analytics.readonly'
TIMEOUT_SECONDS = 45


def _normalized_ga4_private_key() -> str:
    raw = (settings.ga4_private_key or '').strip()
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        raw = raw[1:-1]
    return raw.replace('\\n', '\n').strip()


def _issue_service_account_token() -> str:
    now = int(time.time())
    payload = {
        'iss': settings.ga4_client_email,
        'scope': GA4_SCOPE,
        'aud': GOOGLE_TOKEN_URL,
        'exp': now + 3600,
        'iat': now,
    }
    assertion = jwt.encode(payload, _normalized_ga4_private_key(), algorithm='RS256')
    response = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
            'assertion': assertion,
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()['access_token']


def sync_ga4(db: Session, days: int = 7) -> dict[str, Any]:
    configured = bool(settings.ga4_property_id and settings.ga4_client_email and settings.ga4_private_key)
    upsert_source_config(
        db,
        'ga4',
        configured=configured,
        sync_mode='poll',
        config_json={'property_id': settings.ga4_property_id, 'source_type': 'connector'},
    )
    db.commit()

    if not configured:
        return {'ok': False, 'message': 'GA4 not configured', 'records_processed': 0}

    run = start_sync_run(db, 'ga4', 'run_report', {'days': days})
    db.commit()

    try:
        token = _issue_service_account_token()
        url = f"{settings.ga4_data_api_base_url}/properties/{settings.ga4_property_id}:runReport"
        payload = {
            'dateRanges': [{'startDate': f'{days}daysAgo', 'endDate': 'today'}],
            'metrics': [
                {'name': 'sessions'},
                {'name': 'totalUsers'},
                {'name': 'screenPageViews'},
                {'name': 'bounceRate'},
                {'name': 'purchaseRevenue'},
            ],
            'dimensions': [{'name': 'date'}],
            'limit': 1000,
        }
        response = requests.post(
            url,
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
            },
            json=payload,
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
        rows = body.get('rows', [])
        run.metadata_json = {
            **(run.metadata_json or {}),
            'row_count': len(rows),
            'sample': rows[:3],
            'property_id': settings.ga4_property_id,
        }
        finish_sync_run(db, run, status='success', records_processed=len(rows))
        db.commit()
        return {'ok': True, 'records_processed': len(rows), 'property_id': settings.ga4_property_id}
    except Exception as exc:
        finish_sync_run(db, run, status='failed', error_message=str(exc))
        db.commit()
        return {'ok': False, 'message': str(exc), 'records_processed': 0}
