from __future__ import annotations

import time
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


def _masked_service_account_email() -> str:
    email = (settings.ga4_client_email or '').strip()
    if not email or '@' not in email:
        return 'missing'
    local, domain = email.split('@', 1)
    if len(local) <= 4:
        masked_local = local[0] + '***' if local else '***'
    else:
        masked_local = f'{local[:2]}***{local[-2:]}'
    return f'{masked_local}@{domain}'


def _ga4_invalid_message() -> str:
    return settings.ga4_invalid_message()


def ga4_debug_self_check(days: int = 7) -> dict[str, Any]:
    validation_errors = settings.ga4_validation_errors()
    result: dict[str, Any] = {
        'project_id': settings.ga4_project_id,
        'service_account_email': _masked_service_account_email(),
        'property_id': settings.ga4_property_id,
        'token_scope': GA4_SCOPE,
        'token_acquisition_succeeded': False,
        'run_report_succeeded': False,
        'validation_errors': validation_errors,
    }
    if validation_errors:
        result['message'] = _ga4_invalid_message()
        return result

    try:
        token = _issue_service_account_token()
        result['token_acquisition_succeeded'] = bool(token)
        url = f"{settings.ga4_data_api_base_url}/properties/{settings.ga4_property_id}:runReport"
        payload = {
            'dateRanges': [{'startDate': f'{days}daysAgo', 'endDate': 'today'}],
            'metrics': [{'name': 'sessions'}],
            'dimensions': [{'name': 'date'}],
            'limit': 1,
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
        result['run_report_succeeded'] = response.ok
        if not response.ok:
            result['message'] = response.text[:300]
        return result
    except Exception as exc:
        result['message'] = str(exc)
        return result


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
    validation_errors = settings.ga4_validation_errors()
    configured = bool(settings.ga4_property_id and settings.ga4_client_email and settings.ga4_private_key and settings.ga4_project_id)
    upsert_source_config(
        db,
        'ga4',
        configured=configured,
        sync_mode='poll',
        config_json={'property_id': settings.ga4_property_id, 'source_type': 'connector'},
    )
    db.commit()

    if not configured or validation_errors:
        return {'ok': False, 'message': _ga4_invalid_message(), 'records_processed': 0, 'validation_errors': validation_errors}

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
            'service_account_email': _masked_service_account_email(),
            'project_id': settings.ga4_project_id,
        }
        finish_sync_run(db, run, status='success', records_processed=len(rows))
        db.commit()
        return {'ok': True, 'records_processed': len(rows), 'property_id': settings.ga4_property_id}
    except Exception as exc:
        finish_sync_run(db, run, status='failed', error_message=str(exc))
        db.commit()
        return {'ok': False, 'message': _ga4_invalid_message(), 'records_processed': 0, 'detail': str(exc)}
