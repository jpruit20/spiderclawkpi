from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import requests
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import TelemetryDaily, TelemetrySession
from app.services.source_health import finish_sync_run, refresh_source_health_alerts, start_sync_run, upsert_source_config

settings = get_settings()
TIMEOUT_SECONDS = 60
SOURCE_NAME = "aws_telemetry"
DEFAULT_SESSION_GAP_MINUTES = 20
DEFAULT_LOOKBACK_HOURS = 24 * 30
DEFAULT_MAX_SCAN_PAGES = 10


def _configured() -> bool:
    return bool(
        settings.aws_telemetry_url
        or settings.aws_telemetry_local_path
        or (settings.aws_access_key_id and settings.aws_secret_access_key and settings.aws_telemetry_dynamodb_table and settings.aws_region)
    )


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, Decimal):
            return float(value)
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, Decimal):
            return int(value)
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in {None, ''}:
        return default
    if isinstance(value, (int, float, Decimal)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {'true', '1', 'yes', 'y'}:
        return True
    if normalized in {'false', '0', 'no', 'n'}:
        return False
    return default


def _dt_from_epoch_ms(value: Any) -> datetime | None:
    raw = _as_int(value, 0)
    if raw <= 0:
        return None
    if raw > 10_000_000_000:
        return datetime.fromtimestamp(raw / 1000, tz=timezone.utc)
    return datetime.fromtimestamp(raw, tz=timezone.utc)


def _dt_from_epoch_seconds(value: Any) -> datetime | None:
    raw = _as_int(value, 0)
    if raw <= 0:
        return None
    return datetime.fromtimestamp(raw, tz=timezone.utc)


def _deserialize_dynamodb_attribute(value: Any) -> Any:
    if not isinstance(value, dict) or len(value) != 1:
        return value
    key, payload = next(iter(value.items()))
    if key == 'S':
        return payload
    if key == 'N':
        if '.' in str(payload):
            return float(payload)
        return int(payload)
    if key == 'BOOL':
        return bool(payload)
    if key == 'NULL':
        return None
    if key == 'M':
        return {inner_key: _deserialize_dynamodb_attribute(inner_value) for inner_key, inner_value in payload.items()}
    if key == 'L':
        return [_deserialize_dynamodb_attribute(item) for item in payload]
    return payload


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    if all(isinstance(value, dict) and len(value) == 1 and next(iter(value.keys())) in {'S', 'N', 'BOOL', 'NULL', 'M', 'L'} for value in record.values()):
        return {key: _deserialize_dynamodb_attribute(value) for key, value in record.items()}
    return record


def _load_records_from_file() -> list[dict[str, Any]]:
    import json

    if settings.aws_telemetry_local_path:
        path = Path(settings.aws_telemetry_local_path)
        raw = path.read_text(encoding='utf-8')
    elif settings.aws_telemetry_url:
        headers = {'Accept': 'application/json'}
        if settings.aws_telemetry_api_token:
            headers['Authorization'] = f'Bearer {settings.aws_telemetry_api_token}'
        response = requests.get(settings.aws_telemetry_url, headers=headers, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        raw = response.text
    else:
        return []

    stripped = raw.strip()
    if not stripped:
        return []
    if stripped.startswith('['):
        payload = json.loads(stripped)
        return [_normalize_record(item) for item in payload if isinstance(item, dict)]

    rows: list[dict[str, Any]] = []
    for line in stripped.splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = json.loads(line)
        if isinstance(parsed, dict):
            rows.append(_normalize_record(parsed))
    return rows


def _csv_tokens(value: str | None) -> set[str]:
    return {token.strip().lower() for token in (value or '').split(',') if token.strip()}


def _load_records_from_dynamodb(max_records: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    import boto3
    from botocore.config import Config

    client = boto3.client(
        'dynamodb',
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        config=Config(connect_timeout=5, read_timeout=30, retries={'max_attempts': 2}),
    )
    projection = 'device_id, sample_time, device_data'

    rows: list[dict[str, Any]] = []
    last_evaluated_key = None
    pages = 0
    max_pages = max(1, settings.aws_telemetry_max_scan_pages or DEFAULT_MAX_SCAN_PAGES)
    while len(rows) < max_records and pages < max_pages:
        params = {
            'TableName': settings.aws_telemetry_dynamodb_table,
            'ProjectionExpression': projection,
            'Limit': min(1000, max_records - len(rows)),
        }
        if last_evaluated_key:
            params['ExclusiveStartKey'] = last_evaluated_key
        response = client.scan(**params)
        rows.extend(_normalize_record(item) for item in response.get('Items', []))
        last_evaluated_key = response.get('LastEvaluatedKey')
        pages += 1
        if not last_evaluated_key:
            break
    rows.sort(key=lambda item: _as_int(item.get('sample_time'), 0), reverse=True)
    cutoff_ms = int((datetime.now(timezone.utc) - timedelta(hours=settings.aws_telemetry_lookback_hours or DEFAULT_LOOKBACK_HOURS)).timestamp() * 1000)
    recent_rows = [item for item in rows if _as_int(item.get('sample_time'), 0) >= cutoff_ms]
    bounded_rows = (recent_rows or rows)[:max_records]
    return bounded_rows, {
        'pages_scanned': pages,
        'scan_truncated': bool(last_evaluated_key),
        'raw_rows_scanned': len(rows),
        'recent_rows_after_cutoff': len(recent_rows),
        'cutoff_ms': cutoff_ms,
    }


def _load_records(max_records: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if settings.aws_telemetry_local_path or settings.aws_telemetry_url:
        rows = _load_records_from_file()[:max_records]
        return rows, {
            'pages_scanned': None,
            'scan_truncated': False,
            'raw_rows_scanned': len(rows),
            'recent_rows_after_cutoff': len(rows),
            'cutoff_ms': None,
        }
    return _load_records_from_dynamodb(max_records)


def _reported_state(record: dict[str, Any]) -> dict[str, Any]:
    return ((record.get('device_data') or {}).get('reported') or {}) if isinstance(record.get('device_data'), dict) else {}


def _is_test_device(device_id: str | None, reported: dict[str, Any]) -> bool:
    device_id_value = str(device_id or '').lower()
    model_value = str(reported.get('model') or '').lower()
    mac_value = str(reported.get('mac') or '').lower()
    version_value = str(reported.get('vers') or '').lower()
    prefixes = _csv_tokens(settings.aws_telemetry_test_device_prefixes)
    test_models = _csv_tokens(settings.aws_telemetry_test_models)
    explicit_ids = _csv_tokens(settings.aws_telemetry_test_device_ids)
    if device_id_value and device_id_value in explicit_ids:
        return True
    if model_value and model_value in test_models:
        return True
    if any(device_id_value.startswith(prefix) or model_value.startswith(prefix) or mac_value.startswith(prefix) for prefix in prefixes):
        return True
    blob = ' '.join([device_id_value, model_value, mac_value, version_value])
    return any(token in blob for token in prefixes)


def _build_samples(records: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    excluded_counter: Counter[str] = Counter()
    invalid_records = 0
    duplicate_samples = 0
    sample_keys: set[tuple[str, int]] = set()
    for record in records:
        device_id = record.get('device_id')
        reported = _reported_state(record)
        if not device_id or not isinstance(reported, dict):
            invalid_records += 1
            continue
        if _is_test_device(str(device_id), reported):
            excluded_counter['test_device'] += 1
            continue
        sample_time = _dt_from_epoch_ms(record.get('sample_time'))
        if not sample_time:
            invalid_records += 1
            continue
        sample_key = (str(device_id), _as_int(record.get('sample_time'), 0))
        if sample_key in sample_keys:
            duplicate_samples += 1
            continue
        sample_keys.add(sample_key)
        heat = ((reported.get('heat') or {}).get('t2') or {}) if isinstance(reported.get('heat'), dict) else {}
        grouped[str(device_id)].append({
            'device_id': str(device_id),
            'sample_time': sample_time,
            'engaged': _as_bool(reported.get('engaged')),
            'start_hint': _dt_from_epoch_seconds(heat.get('startTime')),
            'target_temp': _as_float(heat.get('trgt'), 0.0) or None,
            'current_temp': _as_float(reported.get('mainTemp'), 0.0) or None,
            'heating': _as_bool(heat.get('heating')),
            'intensity': _as_float(heat.get('intensity'), 0.0),
            'firmware_version': reported.get('vers'),
            'grill_type': reported.get('model'),
            'rssi': _as_float(reported.get('RSSI'), 0.0),
            'errors': [_as_int(item, 0) for item in (reported.get('errors') or [])],
            'raw_payload': record,
        })
    for device_samples in grouped.values():
        device_samples.sort(key=lambda item: item['sample_time'])
    retained_samples = [sample for device_samples in grouped.values() for sample in device_samples]
    distinct_engaged_devices = len({sample['device_id'] for sample in retained_samples if sample.get('engaged')})
    oldest_sample = min((sample['sample_time'] for sample in retained_samples), default=None)
    newest_sample = max((sample['sample_time'] for sample in retained_samples), default=None)
    return grouped, {
        'devices_observed': len(grouped),
        'distinct_devices_observed': len(grouped),
        'distinct_engaged_devices_observed': distinct_engaged_devices,
        'oldest_sample_timestamp_seen': oldest_sample.isoformat() if oldest_sample else None,
        'newest_sample_timestamp_seen': newest_sample.isoformat() if newest_sample else None,
        'samples_retained': len(retained_samples),
        'excluded_records': sum(excluded_counter.values()),
        'excluded_breakdown': dict(excluded_counter),
        'invalid_records': invalid_records,
        'duplicate_samples': duplicate_samples,
    }


def _stability_score(values: list[float], target_temp: float | None) -> float:
    if not values or not target_temp:
        return 0.0
    avg_abs_error = sum(abs(value - target_temp) for value in values) / len(values)
    score = max(0.0, 1.0 - min(1.0, avg_abs_error / max(target_temp * 0.12, 15.0)))
    return round(score, 4)


def _time_to_stabilization(samples: list[dict[str, Any]], target_temp: float | None) -> int | None:
    if not samples or not target_temp:
        return None
    window = max(8.0, target_temp * 0.05)
    first = samples[0]['sample_time']
    for sample in samples:
        current = sample.get('current_temp')
        if current is None:
            continue
        if abs(current - target_temp) <= window:
            return int((sample['sample_time'] - first).total_seconds())
    return None


def _merge_adjacent_sessions(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not sessions:
        return []
    merged = [sessions[0]]
    merge_gap_seconds = max(0, settings.aws_telemetry_merge_gap_seconds or 0)
    for session in sessions[1:]:
        prior = merged[-1]
        if session['device_id'] == prior['device_id'] and prior['session_end'] and session['session_start']:
            gap_seconds = int((session['session_start'] - prior['session_end']).total_seconds())
            same_target = prior.get('target_temp') == session.get('target_temp')
            if gap_seconds >= 0 and gap_seconds <= merge_gap_seconds and same_target:
                combined_samples = (prior.get('_samples') or []) + (session.get('_samples') or [])
                merged[-1] = _finalize_session(session['device_id'], combined_samples)
                continue
        merged.append(session)
    return merged


def _derive_sessions(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    grouped, sample_stats = _build_samples(records)
    sessions: list[dict[str, Any]] = []
    gap = timedelta(minutes=settings.aws_telemetry_session_gap_minutes or DEFAULT_SESSION_GAP_MINUTES)
    filtered_short_sessions = 0
    merged_session_count = 0

    for device_id, samples in grouped.items():
        active: list[dict[str, Any]] = []
        device_sessions: list[dict[str, Any]] = []
        for sample in samples:
            if not sample['engaged']:
                if active:
                    device_sessions.append(_finalize_session(device_id, active))
                    active = []
                continue
            if active and sample['sample_time'] - active[-1]['sample_time'] > gap:
                device_sessions.append(_finalize_session(device_id, active))
                active = []
            active.append(sample)
        if active:
            device_sessions.append(_finalize_session(device_id, active))
        merged_sessions = _merge_adjacent_sessions(device_sessions)
        merged_session_count += max(0, len(device_sessions) - len(merged_sessions))
        for session in merged_sessions:
            if session['session_duration_seconds'] >= max(0, settings.aws_telemetry_min_session_seconds or 0):
                sessions.append(session)
            else:
                filtered_short_sessions += 1
    return sessions, {
        **sample_stats,
        'sessions_before_merge': None,
        'sessions_merged_away': merged_session_count,
        'short_sessions_filtered': filtered_short_sessions,
        'sessions_final': len(sessions),
    }


def _finalize_session(device_id: str, samples: list[dict[str, Any]]) -> dict[str, Any]:
    first = samples[0]
    last = samples[-1]
    start_hint = first.get('start_hint')
    session_start = start_hint if start_hint and start_hint <= first['sample_time'] else first['sample_time']
    session_end = last['sample_time']
    duration = max(0, int((session_end - session_start).total_seconds()))
    target_values = [sample['target_temp'] for sample in samples if sample.get('target_temp') is not None]
    target_temp = target_values[-1] if target_values else None
    current_temps = [sample['current_temp'] for sample in samples if sample.get('current_temp') is not None]
    intensities = [sample.get('intensity', 0.0) for sample in samples]
    heating_points = sum(1 for sample in samples if sample.get('heating'))
    error_vectors = [sample.get('errors') or [] for sample in samples]
    non_zero_errors = sorted({str(code) for vector in error_vectors for code in vector if _as_int(code, 0) != 0})
    stale_gaps = 0
    for idx in range(1, len(samples)):
        if (samples[idx]['sample_time'] - samples[idx - 1]['sample_time']).total_seconds() > 180:
            stale_gaps += 1
    manual_overrides = 0
    stability = _stability_score([value for value in current_temps if value is not None], target_temp)
    time_to_stable = _time_to_stabilization(samples, target_temp)
    firmware_health = round(max(0.0, 1.0 - min(0.8, stale_gaps * 0.1 + len(non_zero_errors) * 0.08 + max(0.0, 0.35 - stability))), 4)
    manual_override_rate = round(manual_overrides / max(len(samples), 1), 4)
    cook_success = bool(duration >= 1800 and stability >= 0.72 and len(non_zero_errors) == 0)
    reliability = round(max(0.0, min(1.0, firmware_health - min(0.4, stale_gaps * 0.1) - (0 if cook_success else 0.15))), 4)

    return {
        'source_event_id': f"{device_id}:{int(session_start.timestamp())}:{int(session_end.timestamp())}",
        'device_id': device_id,
        'user_id': None,
        'session_id': None,
        'grill_type': first.get('grill_type'),
        'firmware_version': first.get('firmware_version'),
        'target_temp': target_temp,
        'session_start': session_start,
        'session_end': session_end,
        'session_duration_seconds': duration,
        'disconnect_events': stale_gaps,
        'manual_overrides': manual_overrides,
        'error_count': len(non_zero_errors),
        'error_codes_json': non_zero_errors,
        'actual_temp_time_series': [{'ts': sample['sample_time'].isoformat(), 'temp': sample.get('current_temp')} for sample in samples if sample.get('current_temp') is not None],
        'fan_output_time_series': [{'ts': sample['sample_time'].isoformat(), 'value': sample.get('intensity')} for sample in samples],
        'temp_stability_score': stability,
        'time_to_stabilization_seconds': time_to_stable,
        'firmware_health_score': firmware_health,
        'session_reliability_score': reliability,
        'manual_override_rate': manual_override_rate,
        'cook_success': cook_success,
        '_samples': samples,
        'raw_payload': {
            'sample_count': len(samples),
            'heating_share': round(heating_points / max(len(samples), 1), 4),
            'rssi_min': min(sample.get('rssi', 0.0) for sample in samples),
            'rssi_max': max(sample.get('rssi', 0.0) for sample in samples),
            'session_start_hint': start_hint.isoformat() if start_hint else None,
            'last_sample_payload': last.get('raw_payload'),
        },
    }


def sync_aws_telemetry(db: Session, max_records: int = 50000) -> dict[str, Any]:
    configured = _configured()
    upsert_source_config(
        db,
        SOURCE_NAME,
        configured=configured,
        sync_mode='pull',
        config_json={
            'source_type': 'connector',
            'input': 'dynamodb' if settings.aws_telemetry_dynamodb_table else 'url' if settings.aws_telemetry_url else 'local_path' if settings.aws_telemetry_local_path else None,
            'table': settings.aws_telemetry_dynamodb_table,
            'region': settings.aws_region,
        },
    )
    db.commit()

    if not configured:
        return {'ok': False, 'skipped': True, 'records_processed': 0, 'message': 'AWS telemetry source is not configured'}

    run = start_sync_run(db, SOURCE_NAME, 'sync_telemetry', {'max_records': max_records})
    db.commit()

    try:
        records, read_stats = _load_records(max_records)
        sessions, derivation_stats = _derive_sessions(records)
        db.execute(delete(TelemetrySession))
        db.execute(delete(TelemetryDaily))
        db.flush()

        daily = defaultdict(lambda: {
            'sessions': 0,
            'users': set(),
            'cook_success': 0,
            'disconnect_sessions': 0,
            'stability_sum': 0.0,
            'stabilization_sum': 0.0,
            'stabilization_count': 0,
            'override_sum': 0.0,
            'firmware_sum': 0.0,
            'reliability_sum': 0.0,
            'error_sessions': 0,
        })

        for session in sessions:
            db_session_payload = {key: value for key, value in session.items() if key != '_samples'}
            db.add(TelemetrySession(**db_session_payload))
            business_date = session['session_start'].date()
            bucket = daily[business_date]
            bucket['sessions'] += 1
            if session.get('user_id'):
                bucket['users'].add(str(session['user_id']))
            if session['cook_success']:
                bucket['cook_success'] += 1
            if session['disconnect_events'] > 0:
                bucket['disconnect_sessions'] += 1
            bucket['stability_sum'] += session['temp_stability_score']
            if session['time_to_stabilization_seconds'] is not None:
                bucket['stabilization_sum'] += session['time_to_stabilization_seconds']
                bucket['stabilization_count'] += 1
            bucket['override_sum'] += session['manual_override_rate']
            bucket['firmware_sum'] += session['firmware_health_score']
            bucket['reliability_sum'] += session['session_reliability_score']
            if session['error_count'] > 0:
                bucket['error_sessions'] += 1

        for business_date, values in daily.items():
            total_sessions = values['sessions']
            db.add(TelemetryDaily(
                business_date=business_date,
                sessions=total_sessions,
                connected_users=len(values['users']),
                cook_success_rate=round(values['cook_success'] / max(total_sessions, 1), 4),
                disconnect_rate=round(values['disconnect_sessions'] / max(total_sessions, 1), 4),
                temp_stability_score=round(values['stability_sum'] / max(total_sessions, 1), 4),
                avg_time_to_stabilization_seconds=round(values['stabilization_sum'] / max(values['stabilization_count'], 1), 2),
                manual_override_rate=round(values['override_sum'] / max(total_sessions, 1), 4),
                firmware_health_score=round(values['firmware_sum'] / max(total_sessions, 1), 4),
                session_reliability_score=round(values['reliability_sum'] / max(total_sessions, 1), 4),
                error_rate=round(values['error_sessions'] / max(total_sessions, 1), 4),
            ))

        run.metadata_json = {
            **(run.metadata_json or {}),
            'records_loaded': len(records),
            'sessions_derived': len(sessions),
            'devices_observed': derivation_stats.get('devices_observed'),
            'distinct_devices_observed': derivation_stats.get('distinct_devices_observed'),
            'distinct_engaged_devices_observed': derivation_stats.get('distinct_engaged_devices_observed'),
            'oldest_sample_timestamp_seen': derivation_stats.get('oldest_sample_timestamp_seen'),
            'newest_sample_timestamp_seen': derivation_stats.get('newest_sample_timestamp_seen'),
            'samples_retained': derivation_stats.get('samples_retained'),
            'excluded_records': derivation_stats.get('excluded_records'),
            'excluded_breakdown': derivation_stats.get('excluded_breakdown'),
            'invalid_records': derivation_stats.get('invalid_records'),
            'duplicate_samples': derivation_stats.get('duplicate_samples'),
            'sessions_merged_away': derivation_stats.get('sessions_merged_away'),
            'short_sessions_filtered': derivation_stats.get('short_sessions_filtered'),
            'pages_scanned': read_stats.get('pages_scanned'),
            'scan_truncated': read_stats.get('scan_truncated'),
            'raw_rows_scanned': read_stats.get('raw_rows_scanned'),
            'recent_rows_after_cutoff': read_stats.get('recent_rows_after_cutoff'),
            'cutoff_ms': read_stats.get('cutoff_ms'),
            'max_record_cap_hit': len(records) >= max_records,
            'session_gap_timeout_minutes': settings.aws_telemetry_session_gap_minutes or DEFAULT_SESSION_GAP_MINUTES,
            'coverage_summary': (
                f"Observed {derivation_stats.get('distinct_devices_observed') or 0} devices "
                f"({derivation_stats.get('distinct_engaged_devices_observed') or 0} engaged) from a bounded direct DynamoDB read; "
                f"scan truncated={bool(read_stats.get('scan_truncated'))}, max_record_cap_hit={len(records) >= max_records}."
            ),
            'days_materialized': len(daily),
            'max_records': max_records,
            'sample_source': 'dynamodb' if settings.aws_telemetry_dynamodb_table else 'url' if settings.aws_telemetry_url else 'local_path',
            'table': settings.aws_telemetry_dynamodb_table,
            'region': settings.aws_region,
        }
        finish_sync_run(db, run, status='success', records_processed=len(records))
        refresh_source_health_alerts(db)
        db.commit()
        return {'ok': True, 'records_processed': len(records), 'sessions_derived': len(sessions), 'days_materialized': len(daily)}
    except Exception as exc:
        finish_sync_run(db, run, status='failed', error_message=str(exc))
        refresh_source_health_alerts(db)
        db.commit()
        return {'ok': False, 'records_processed': 0, 'message': str(exc)}
