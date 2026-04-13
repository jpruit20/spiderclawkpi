from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any
from urllib.parse import urlparse

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import ClarityPageMetric
from app.services.source_health import finish_sync_run, start_sync_run, upsert_source_config

logger = logging.getLogger(__name__)
settings = get_settings()
TIMEOUT_SECONDS = 45
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 30

# Metric keys returned by the Clarity export API
METRIC_KEYS = [
    "DeadClickCount",
    "ExcessiveScroll",
    "RageClickCount",
    "QuickbackClick",
    "ScriptErrorCount",
    "ErrorClickCount",
    "ScrollDepth",
    "Traffic",
    "EngagementTime",
]

# Mapping from Clarity metric name to the fields we track
METRIC_FIELD_MAP = {
    "DeadClickCount": "dead_click",
    "RageClickCount": "rage_click",
    "QuickbackClick": "quick_back",
    "ScriptErrorCount": "script_error",
    "ExcessiveScroll": "excessive_scroll",
    "Traffic": "traffic",
}


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


def _extract_page_path(url: str) -> str:
    """Extract path from URL, stripping domain and query params."""
    try:
        parsed = urlparse(url)
        path = parsed.path or '/'
        # Normalize trailing slash
        if path != '/' and path.endswith('/'):
            path = path.rstrip('/')
        return path
    except Exception:
        return url


def _classify_page_type(path: str) -> str:
    """Classify page_type based on URL path."""
    path_lower = path.lower()
    if path_lower == '/' or path_lower == '':
        return 'home'
    if path_lower.startswith('/products/') or path_lower == '/products':
        return 'product'
    if path_lower.startswith('/collections/') or path_lower == '/collections':
        return 'collection'
    if path_lower.startswith('/cart') or path_lower == '/cart':
        return 'cart'
    if path_lower.startswith('/account'):
        return 'account'
    return 'other'


def _compute_friction_score(
    dead_click_pct: float,
    rage_click_pct: float,
    quick_back_pct: float,
    script_error_pct: float,
    excessive_scroll_pct: float,
) -> float:
    """Compute composite friction score 0-100.

    Input percentages are 0-100 scale (e.g. 50 means 50%).
    Weights sum to 1.0 so the output is also 0-100.
    """
    score = (
        dead_click_pct * 0.20
        + rage_click_pct * 0.30
        + quick_back_pct * 0.25
        + script_error_pct * 0.15
        + excessive_scroll_pct * 0.10
    )
    return min(100.0, max(0.0, score))


def _parse_response_to_page_metrics(body: Any, snapshot_date: date) -> list[dict]:
    """Parse the Clarity API response into per-URL aggregated records.

    The response is a list of metric objects, each with an `information` array
    of per-URL records. We need to group by URL and aggregate across metrics.
    """
    # Collect per-URL data across all metrics
    url_data: dict[str, dict[str, Any]] = {}

    items = body if isinstance(body, list) else [body] if isinstance(body, dict) else []

    for item in items:
        if not isinstance(item, dict):
            continue

        metric_name = item.get('metricName') or item.get('metric_name') or item.get('name', '')
        information = item.get('information', [])
        if not isinstance(information, list):
            continue

        for record in information:
            if not isinstance(record, dict):
                continue
            url = record.get('Url') or record.get('url', '')
            if not url:
                continue

            if url not in url_data:
                url_data[url] = {
                    'url': url,
                    'sessions': 0,
                    'dead_clicks': 0,
                    'dead_click_pct': 0.0,
                    'rage_clicks': 0,
                    'rage_click_pct': 0.0,
                    'quick_backs': 0,
                    'quick_back_pct': 0.0,
                    'script_errors': 0,
                    'script_error_pct': 0.0,
                    'excessive_scroll': 0,
                    'excessive_scroll_pct': 0.0,
                }

            entry = url_data[url]
            sessions_count = int(record.get('sessionsCount', 0) or 0)
            with_metric_pct = float(record.get('sessionsWithMetricPercentage', 0) or 0)
            sub_total = int(record.get('subTotal', 0) or 0)

            # Use the highest sessions count we see across metrics for this URL
            if sessions_count > entry['sessions']:
                entry['sessions'] = sessions_count

            field = METRIC_FIELD_MAP.get(metric_name)
            if field == 'dead_click':
                entry['dead_clicks'] = sub_total
                entry['dead_click_pct'] = with_metric_pct
            elif field == 'rage_click':
                entry['rage_clicks'] = sub_total
                entry['rage_click_pct'] = with_metric_pct
            elif field == 'quick_back':
                entry['quick_backs'] = sub_total
                entry['quick_back_pct'] = with_metric_pct
            elif field == 'script_error':
                entry['script_errors'] = sub_total
                entry['script_error_pct'] = with_metric_pct
            elif field == 'excessive_scroll':
                entry['excessive_scroll'] = sub_total
                entry['excessive_scroll_pct'] = with_metric_pct
            elif field == 'traffic':
                # Traffic metric gives authoritative sessions count
                entry['sessions'] = max(entry['sessions'], sessions_count)

    # Build final records
    results = []
    for url, data in url_data.items():
        page_path = _extract_page_path(url)
        page_type = _classify_page_type(page_path)
        friction = _compute_friction_score(
            data['dead_click_pct'],
            data['rage_click_pct'],
            data['quick_back_pct'],
            data['script_error_pct'],
            data.get('excessive_scroll_pct', 0.0),
        )
        results.append({
            'url': url,
            'page_path': page_path,
            'page_type': page_type,
            'sessions': data['sessions'],
            'dead_clicks': data['dead_clicks'],
            'dead_click_pct': data['dead_click_pct'],
            'rage_clicks': data['rage_clicks'],
            'rage_click_pct': data['rage_click_pct'],
            'quick_backs': data['quick_backs'],
            'quick_back_pct': data['quick_back_pct'],
            'script_errors': data['script_errors'],
            'script_error_pct': data['script_error_pct'],
            'excessive_scroll': data['excessive_scroll'],
            'friction_score': round(friction, 2),
            'snapshot_date': snapshot_date,
        })

    return results


def _upsert_page_metrics(db: Session, records: list[dict]) -> int:
    """Upsert parsed records into clarity_page_metrics. Returns count of upserted rows."""
    if not records:
        return 0

    upserted = 0
    for record in records:
        db.execute(
            text("""
                INSERT INTO clarity_page_metrics
                    (url, page_path, page_type, sessions, dead_clicks, dead_click_pct,
                     rage_clicks, rage_click_pct, quick_backs, quick_back_pct,
                     script_errors, script_error_pct, excessive_scroll,
                     friction_score, snapshot_date, created_at, updated_at)
                VALUES
                    (:url, :page_path, :page_type, :sessions, :dead_clicks, :dead_click_pct,
                     :rage_clicks, :rage_click_pct, :quick_backs, :quick_back_pct,
                     :script_errors, :script_error_pct, :excessive_scroll,
                     :friction_score, :snapshot_date, NOW(), NOW())
                ON CONFLICT (page_path, snapshot_date) DO UPDATE SET
                    url = EXCLUDED.url,
                    page_type = EXCLUDED.page_type,
                    sessions = EXCLUDED.sessions,
                    dead_clicks = EXCLUDED.dead_clicks,
                    dead_click_pct = EXCLUDED.dead_click_pct,
                    rage_clicks = EXCLUDED.rage_clicks,
                    rage_click_pct = EXCLUDED.rage_click_pct,
                    quick_backs = EXCLUDED.quick_backs,
                    quick_back_pct = EXCLUDED.quick_back_pct,
                    script_errors = EXCLUDED.script_errors,
                    script_error_pct = EXCLUDED.script_error_pct,
                    excessive_scroll = EXCLUDED.excessive_scroll,
                    friction_score = EXCLUDED.friction_score,
                    updated_at = NOW()
            """),
            record,
        )
        upserted += 1

    return upserted


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
        params = {'numOfDays': max(1, min(days, 3)), 'dimension1': 'URL'}
        headers = {'Authorization': f'Bearer {settings.clarity_api_token}', 'Accept': 'application/json'}

        # Retry loop with exponential backoff for rate-limiting (429)
        response = None
        last_error = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = requests.get(url, params=params, headers=headers, timeout=TIMEOUT_SECONDS)
                if response.status_code == 429:
                    retry_after = response.headers.get('Retry-After')
                    wait_seconds = int(retry_after) if retry_after and retry_after.isdigit() else BASE_BACKOFF_SECONDS * (2 ** attempt)
                    wait_seconds = min(wait_seconds, 300)  # cap at 5 minutes
                    if attempt < MAX_RETRIES:
                        logger.warning(f"Clarity 429 rate-limited (attempt {attempt + 1}/{MAX_RETRIES + 1}), waiting {wait_seconds}s before retry")
                        time.sleep(wait_seconds)
                        continue
                    else:
                        response.raise_for_status()  # will raise on final attempt
                response.raise_for_status()
                break  # success
            except requests.exceptions.HTTPError as e:
                last_error = e
                if response is not None and response.status_code == 429 and attempt < MAX_RETRIES:
                    continue  # already handled above
                raise
            except requests.exceptions.Timeout as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    wait_seconds = BASE_BACKOFF_SECONDS * (2 ** attempt)
                    logger.warning(f"Clarity timeout (attempt {attempt + 1}/{MAX_RETRIES + 1}), waiting {wait_seconds}s before retry")
                    time.sleep(wait_seconds)
                    continue
                raise

        body = response.json()
        records = _extract_clarity_records(body)

        # Parse and upsert per-URL page metrics
        snapshot_date = date.today()
        page_records = _parse_response_to_page_metrics(body, snapshot_date)
        upserted = _upsert_page_metrics(db, page_records)

        run.metadata_json = {
            **(run.metadata_json or {}),
            'project_id': settings.clarity_project_id,
            'request_url': response.url,
            'sample': records[:3] if records else body,
            'page_metrics_upserted': upserted,
            'unique_urls_parsed': len(page_records),
            'attempts': attempt + 1,
        }
        finish_sync_run(db, run, status='success', records_processed=len(records))
        db.commit()
        return {
            'ok': True,
            'records_processed': len(records),
            'page_metrics_upserted': upserted,
            'project_id': settings.clarity_project_id,
            'attempts': attempt + 1,
        }
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
