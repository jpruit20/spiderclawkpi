from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from statistics import median
from typing import Any

from sqlalchemy import and_, desc, distinct, func, select
from sqlalchemy.orm import Session

from app.models import SourceSyncRun, TelemetryStreamEvent


def _safe_div(num: float, den: float) -> float:
    if den == 0:
        return 0.0
    return round(num / den, 4)


def summarize_stream_telemetry(db: Session, stream_events: list[TelemetryStreamEvent]) -> dict[str, Any]:
    now = max((event.sample_timestamp for event in stream_events if event.sample_timestamp), default=None)
    if now is None:
        now = max((event.created_at for event in stream_events if event.created_at), default=None)

    latest_run = db.execute(
        select(SourceSyncRun)
        .where(SourceSyncRun.source_name == 'aws_telemetry', SourceSyncRun.status == 'success')
        .order_by(desc(SourceSyncRun.started_at))
        .limit(1)
    ).scalars().first()
    metadata = latest_run.metadata_json if latest_run else {}

    device_buckets: dict[str, list[TelemetryStreamEvent]] = defaultdict(list)
    latest_by_device: dict[str, TelemetryStreamEvent] = {}
    latest_event_count_by_device: Counter[str] = Counter()
    latest_firmware_by_device: dict[str, str] = {}
    latest_grill_type_by_device: dict[str, str] = {}
    low_rssi_devices = set()
    error_devices = set()
    target_temps = Counter()

    for event in stream_events:
        device_buckets[event.device_id].append(event)
        current_latest = latest_by_device.get(event.device_id)
        if current_latest is None or ((event.sample_timestamp or event.created_at) and (current_latest.sample_timestamp or current_latest.created_at) and (event.sample_timestamp or event.created_at) > (current_latest.sample_timestamp or current_latest.created_at)):
            latest_by_device[event.device_id] = event
        if event.rssi is not None and event.rssi <= -75:
            low_rssi_devices.add(event.device_id)
        if event.error_codes_json and any(int(code) != 0 for code in event.error_codes_json):
            error_devices.add(event.device_id)
        if event.target_temp is not None:
            target_temps[str(int(event.target_temp))] += 1

    session_lengths = [len(events) for events in device_buckets.values()]
    distinct_devices = len(device_buckets)
    newest = max((event.sample_timestamp for event in stream_events if event.sample_timestamp), default=None)
    oldest = min((event.sample_timestamp for event in stream_events if event.sample_timestamp), default=None)

    horizon_start = (now - timedelta(hours=24)) if now else None
    active_counts = {'5m': 0, '15m': 0, '60m': 0, '24h': 0}
    latest_rows: list[TelemetryStreamEvent] = []
    if now and horizon_start:
        active_counts['5m'] = int(db.execute(
            select(func.count(distinct(TelemetryStreamEvent.device_id)))
            .where(TelemetryStreamEvent.sample_timestamp >= now - timedelta(minutes=5))
        ).scalar() or 0)
        active_counts['15m'] = int(db.execute(
            select(func.count(distinct(TelemetryStreamEvent.device_id)))
            .where(TelemetryStreamEvent.sample_timestamp >= now - timedelta(minutes=15))
        ).scalar() or 0)
        active_counts['60m'] = int(db.execute(
            select(func.count(distinct(TelemetryStreamEvent.device_id)))
            .where(TelemetryStreamEvent.sample_timestamp >= now - timedelta(minutes=60))
        ).scalar() or 0)
        active_counts['24h'] = int(db.execute(
            select(func.count(distinct(TelemetryStreamEvent.device_id)))
            .where(TelemetryStreamEvent.sample_timestamp >= horizon_start)
        ).scalar() or 0)

        latest_ts_subquery = (
            select(
                TelemetryStreamEvent.device_id.label('device_id'),
                func.max(TelemetryStreamEvent.sample_timestamp).label('latest_ts'),
            )
            .where(TelemetryStreamEvent.sample_timestamp >= horizon_start)
            .group_by(TelemetryStreamEvent.device_id)
            .subquery()
        )
        latest_rows = db.execute(
            select(TelemetryStreamEvent)
            .join(
                latest_ts_subquery,
                and_(
                    TelemetryStreamEvent.device_id == latest_ts_subquery.c.device_id,
                    TelemetryStreamEvent.sample_timestamp == latest_ts_subquery.c.latest_ts,
                ),
            )
            .order_by(desc(TelemetryStreamEvent.sample_timestamp))
        ).scalars().all()

    engaged_latest_devices = set()
    for event in latest_rows:
        device_id = event.device_id
        if event.engaged:
            engaged_latest_devices.add(device_id)
        if event.firmware_version:
            latest_firmware_by_device[device_id] = event.firmware_version
        if event.grill_type:
            latest_grill_type_by_device[device_id] = event.grill_type
        latest_event_count_by_device[device_id] += 1

    if not latest_rows:
        for device_id, event in latest_by_device.items():
            if event.engaged:
                engaged_latest_devices.add(device_id)
            if event.firmware_version:
                latest_firmware_by_device[device_id] = event.firmware_version
            if event.grill_type:
                latest_grill_type_by_device[device_id] = event.grill_type
            latest_event_count_by_device[device_id] += 1

    firmware = Counter(latest_firmware_by_device.values())
    grill_types = Counter(latest_grill_type_by_device.values())

    primary_active_devices_count = active_counts['15m'] or active_counts['5m'] or len(engaged_latest_devices)
    latest = {
        'business_date': newest.date().isoformat() if newest else None,
        'sessions': primary_active_devices_count,
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
            'engaged_latest_devices': len(engaged_latest_devices),
            'active_devices_last_5m': active_counts['5m'],
            'active_devices_last_15m': active_counts['15m'],
            'active_devices_last_60m': active_counts['60m'],
            'active_devices_last_24h': active_counts['24h'],
            'sessions_derived': primary_active_devices_count,
            'recent_activity_window_minutes': 15,
            'average_events_per_device_in_slice': round(sum(session_lengths) / max(len(session_lengths), 1), 2),
            'median_events_per_device_in_slice': median(session_lengths) if session_lengths else 0,
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
            'sessions_derived': primary_active_devices_count,
            'days_materialized': 1 if latest.get('business_date') else 0,
            'distinct_devices_observed': distinct_devices,
            'engaged_latest_devices': len(engaged_latest_devices),
            'active_devices_last_5m': active_counts['5m'],
            'active_devices_last_15m': active_counts['15m'],
            'active_devices_last_60m': active_counts['60m'],
            'active_devices_last_24h': active_counts['24h'],
            'oldest_sample_timestamp_seen': oldest.isoformat() if oldest else None,
            'newest_sample_timestamp_seen': newest.isoformat() if newest else None,
            'max_record_cap_hit': False,
            'scan_truncated': False,
            'coverage_summary': f'Observed {distinct_devices} devices in the loaded stream slice; full-table counts show {active_counts["15m"]} devices active in the last 15 minutes, {active_counts["60m"]} in 60 minutes, and {len(engaged_latest_devices)} engaged on latest state across the last 24 hours.',
        },
        'confidence': {
            'global_completeness': 'estimated',
            'session_derivation': 'recent_activity_proxy',
            'disconnect_detection': 'proxy',
            'cook_success': 'estimated',
            'manual_override': 'unavailable',
            'reason': f'Live stream-backed telemetry is now using full-table recent-activity windows ({active_counts["5m"]} devices in 5m, {active_counts["15m"]} in 15m, {active_counts["60m"]} in 60m) plus latest-state engagement across the last 24h; this is more honest than counting engaged devices as sessions, but still not a canonical fleet session model.',
        },
    }
