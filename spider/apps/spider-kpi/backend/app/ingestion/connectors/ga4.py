from __future__ import annotations

import time
from datetime import date
from typing import Any

import jwt
import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ShopifyAnalyticsDaily
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
    return settings.masked_ga4_client_email()


def _ga4_invalid_message() -> str:
    return settings.ga4_invalid_message()


def ga4_debug_self_check(days: int = 7) -> dict[str, Any]:
    validation_errors = settings.ga4_validation_errors()
    result: dict[str, Any] = {
        'project_id': settings.ga4_project_id,
        'service_account_email': _masked_service_account_email(),
        'property_id': settings.ga4_property_id,
        'token_scope': GA4_SCOPE,
        'token_success': False,
        'api_success': False,
        'validation_errors': validation_errors,
        'error_message': None,
    }
    if validation_errors:
        result['error_message'] = _ga4_invalid_message()
        return result

    try:
        token = _issue_service_account_token()
        result['token_success'] = bool(token)
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
        result['api_success'] = response.ok
        if not response.ok:
            result['error_message'] = response.text[:300]
        return result
    except Exception as exc:
        result['error_message'] = str(exc)
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


def _upsert_ga4_rows(db: Session, rows: list[dict[str, Any]]) -> int:
    """Upsert one ShopifyAnalyticsDaily row per GA4 day-aggregated row.

    GA4 runReport returns each row as
        {dimensionValues: [{value: 'YYYYMMDD'}],
         metricValues: [{value: '<sessions>'}, {value: '<users>'},
                        {value: '<page_views>'}, {value: '<bounce_rate>'},
                        {value: '<purchase_revenue>'}]}
    matching the metric ordering in the runReport payload below. We
    persist sessions / users / page_views / bounce_rate; conversion_rate
    and add_to_cart_rate are computed downstream from KPIDaily.
    """
    upserted = 0
    for row in rows:
        dim_values = row.get('dimensionValues', [])
        metric_values = row.get('metricValues', [])
        if not dim_values or len(metric_values) < 4:
            continue
        raw_date = (dim_values[0] or {}).get('value', '') or ''
        if len(raw_date) != 8 or not raw_date.isdigit():
            continue
        try:
            business_date = date(int(raw_date[0:4]), int(raw_date[4:6]), int(raw_date[6:8]))
        except ValueError:
            continue

        def _f(idx: int) -> float:
            try:
                return float((metric_values[idx] or {}).get('value') or 0)
            except (TypeError, ValueError):
                return 0.0

        existing = db.execute(
            select(ShopifyAnalyticsDaily).where(ShopifyAnalyticsDaily.business_date == business_date)
        ).scalar_one_or_none()
        if existing is None:
            existing = ShopifyAnalyticsDaily(business_date=business_date)
            db.add(existing)
        existing.sessions = _f(0)
        existing.users = _f(1)
        existing.page_views = _f(2)
        existing.bounce_rate = _f(3)
        upserted += 1
    return upserted


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
        upserted = _upsert_ga4_rows(db, rows)
        run.metadata_json = {
            **(run.metadata_json or {}),
            'row_count': len(rows),
            'rows_upserted': upserted,
            'sample': rows[:3],
            'property_id': settings.ga4_property_id,
            'service_account_email': _masked_service_account_email(),
            'project_id': settings.ga4_project_id,
        }
        finish_sync_run(db, run, status='success', records_processed=upserted)
        db.commit()
        return {'ok': True, 'records_processed': upserted, 'property_id': settings.ga4_property_id}
    except Exception as exc:
        finish_sync_run(db, run, status='failed', error_message=str(exc))
        db.commit()
        return {'ok': False, 'message': _ga4_invalid_message(), 'records_processed': 0, 'detail': str(exc)}
