from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import SourceSyncRun, TelemetryStreamEvent


def _safe_div(num: float, den: float) -> float:
    if den == 0:
        return 0.0
    return round(num / den, 4)


def summarize_stream_telemetry(db: Session, stream_events: list[TelemetryStreamEvent]) -> dict[str, Any]:
    latest_run = db.execute(
        select(SourceSyncRun)
        .where(SourceSyncRun.source_name == 'aws_telemetry', SourceSyncRun.status == 'success')
        .order_by(desc(SourceSyncRun.started_at))
        .limit(1)
    ).scalars().first()
    metadata = latest_run.metadata_json if latest_run else {}

    device_buckets: dict[str, list[TelemetryStreamEvent]] = defaultdict(list)
    firmware = Counter()
    grill_types = Counter()
    low_rssi_devices = set()
    error_devices = set()
    engaged_devices = set()
    target_temps = Counter()

    for event in stream_events:
        device_buckets[event.device_id].append(event)
        if event.firmware_version:
            firmware[event.firmware_version] += 1
        if event.grill_type:
            grill_types[event.grill_type] += 1
        if event.rssi is not None and event.rssi <= -75:
            low_rssi_devices.add(event.device_id)
        if event.error_codes_json and any(int(code) != 0 for code in event.error_codes_json):
            error_devices.add(event.device_id)
        if event.engaged:
            engaged_devices.add(event.device_id)
        if event.target_temp is not None:
            target_temps[str(int(event.target_temp))] += 1

    session_lengths = [len(events) for events in device_buckets.values()]
    distinct_devices = len(device_buckets)
    distinct_engaged_devices = len(engaged_devices)
    newest = max((event.sample_timestamp for event in stream_events if event.sample_timestamp), default=None)
    oldest = min((event.sample_timestamp for event in stream_events if event.sample_timestamp), default=None)
    latest = {
        'business_date': newest.date().isoformat() if newest else None,
        'sessions': distinct_engaged_devices,
        'connected_users': 0,
        'cook_success_rate': 0.0,
        'disconnect_rate': _safe_div(len(low_rssi_devices), distinct_devices or 1),
        'temp_stability_score': 0.0,
        'avg_time_to_stabilization_seconds': 0,
        'manual_override_rate': 0.0,
        'firmware_health_score': round(max(0.0, 1 - _safe_div(len(error_devices), distinct_devices or 1)), 4),
        'session_reliability_score': round(max(0.0, 1 - _safe_div(len(low_rssi_devices | error_devices), distinct_devices or 1)), 4),
        'error_rate': _safe_div(len(error_devices), distinct_devices or 1),
    }

    return {
        'latest': latest,
        'daily': [latest] if latest.get('business_date') else [],
        'firmware_health': [
            {
                'key': key,
                'sessions': count,
                'disconnect_rate': 0.0,
                'manual_override_rate': 0.0,
                'failure_rate': 0.0,
                'health_score': 1.0,
                'severity': 'medium' if count == 1 else 'low',
            }
            for key, count in firmware.most_common(10)
        ],
        'grill_type_health': [
            {
                'key': key,
                'sessions': count,
                'disconnect_rate': 0.0,
                'manual_override_rate': 0.0,
                'failure_rate': 0.0,
                'health_score': 1.0,
                'severity': 'medium' if count == 1 else 'low',
            }
            for key, count in grill_types.most_common(10)
        ],
        'top_error_codes': [],
        'top_issue_patterns': [
            {'pattern': 'stream_low_rssi_presence', 'count': len(low_rssi_devices)} if low_rssi_devices else {'pattern': 'stream_healthy', 'count': distinct_devices}
        ],
        'slice_snapshot': {
            'distinct_devices_observed': distinct_devices,
            'distinct_engaged_devices_observed': distinct_engaged_devices,
            'sessions_derived': distinct_engaged_devices,
            'average_session_duration_seconds': round(sum(session_lengths) / max(len(session_lengths), 1), 2),
            'median_session_duration_seconds': median(session_lengths) if session_lengths else 0,
            'low_rssi_session_rate': _safe_div(len(low_rssi_devices), distinct_devices or 1),
            'error_vector_presence_rate': _safe_div(len(error_devices), distinct_devices or 1),
            'target_temp_distribution': [{'target_temp': key, 'count': count} for key, count in target_temps.most_common(10)],
        },
        'collection_metadata': {
            'source': 'sg_device_shadows_stream',
            'region': metadata.get('region'),
            'table': metadata.get('table'),
            'sample_source': 'dynamodb_stream',
            'records_loaded': len(stream_events),
            'sessions_derived': distinct_engaged_devices,
            'days_materialized': 1 if latest.get('business_date') else 0,
            'distinct_devices_observed': distinct_devices,
            'distinct_engaged_devices_observed': distinct_engaged_devices,
            'oldest_sample_timestamp_seen': oldest.isoformat() if oldest else None,
            'newest_sample_timestamp_seen': newest.isoformat() if newest else None,
            'max_record_cap_hit': False,
            'scan_truncated': False,
            'coverage_summary': f'Observed {distinct_devices} devices ({distinct_engaged_devices} engaged) from live DynamoDB stream events.',
        },
        'confidence': {
            'global_completeness': 'estimated',
            'session_derivation': 'estimated',
            'disconnect_detection': 'proxy',
            'cook_success': 'estimated',
            'manual_override': 'unavailable',
            'reason': f'Live stream-backed telemetry observed {distinct_devices} devices; still not canonical until parity/backfill validation is complete.',
        },
    }
