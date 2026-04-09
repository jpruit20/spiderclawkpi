from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
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


@dataclass
class DerivedSession:
    device_id: str
    start_ts: Any
    end_ts: Any
    events: list[TelemetryStreamEvent]
    reached_target: bool
    stabilized: bool
    completed: bool
    disconnect_proxy: bool
    session_success: bool
    overshoot: bool
    stability_score: float
    overshoot_rate: float
    time_to_stabilize_seconds: int | None
    avg_rssi: float | None
    min_rssi: float | None
    firmware_version: str | None
    grill_type: str | None
    target_temp: float | None
    error_count: int
    archetype: str
    probe_count: int
    probe_failure: bool
    avg_pit_probe_delta: float | None
    dropoff_reason: str


def _extract_probe_values(payload: dict[str, Any] | None) -> list[float]:
    if not isinstance(payload, dict):
        return []
    reported = payload.get('reported') if isinstance(payload.get('reported'), dict) else payload
    probe_values: list[float] = []
    candidate_keys = ['probe_temps', 'probes', 'probeTemps', 'probeReadings', 'food_temps', 'foodTemps']
    for key in candidate_keys:
        value = reported.get(key)
        if isinstance(value, list):
            for item in value:
                try:
                    probe_values.append(float(item))
                except (TypeError, ValueError):
                    continue
        elif isinstance(value, dict):
            for item in value.values():
                if isinstance(item, dict):
                    for nested in item.values():
                        try:
                            probe_values.append(float(nested))
                        except (TypeError, ValueError):
                            continue
                else:
                    try:
                        probe_values.append(float(item))
                    except (TypeError, ValueError):
                        continue
    return [value for value in probe_values if value > 0]


def _classify_rssi_bucket(value: float | None) -> str:
    if value is None:
        return 'unknown'
    if value <= -85:
        return '<=-85 dBm'
    if value <= -75:
        return '-84 to -75 dBm'
    if value <= -65:
        return '-74 to -65 dBm'
    return '>-65 dBm'


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 1)
    idx = (len(ordered) - 1) * q
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    fraction = idx - lo
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * fraction, 1)


def _derive_sessions(device_id: str, events: list[TelemetryStreamEvent], gap_minutes: int = 45) -> list[DerivedSession]:
    if not events:
        return []
    ordered = sorted(events, key=lambda item: item.sample_timestamp or item.created_at)
    grouped: list[list[TelemetryStreamEvent]] = []
    current: list[TelemetryStreamEvent] = []
    previous_ts = None
    for event in ordered:
        ts = event.sample_timestamp or event.created_at
        if ts is None:
            continue
        if previous_ts and ts - previous_ts > timedelta(minutes=gap_minutes):
            if current:
                grouped.append(current)
            current = []
        current.append(event)
        previous_ts = ts
    if current:
        grouped.append(current)

    sessions: list[DerivedSession] = []
    for group in grouped:
        first = group[0]
        last = group[-1]
        temps = [float(item.current_temp) for item in group if item.current_temp is not None]
        targets = [float(item.target_temp) for item in group if item.target_temp is not None and float(item.target_temp) > 0]
        target_temp = median(targets) if targets else None
        errors = sum(sum(1 for code in (item.error_codes_json or []) if int(code) != 0) for item in group)
        rssis = [float(item.rssi) for item in group if item.rssi is not None]
        reached_target = False
        stabilize_ts = None
        overshoot = False
        stable_hits = 0
        temp_deltas: list[float] = []
        probe_counts: list[int] = []
        probe_failures = 0
        pit_probe_deltas: list[float] = []

        for item in group:
            current_temp = float(item.current_temp) if item.current_temp is not None else None
            if target_temp is not None and current_temp is not None:
                delta = current_temp - target_temp
                temp_deltas.append(abs(delta))
                if current_temp >= target_temp - 10:
                    reached_target = True
                if current_temp > target_temp + 15:
                    overshoot = True
                if abs(delta) <= 15:
                    stable_hits += 1
                    if stable_hits >= 3 and stabilize_ts is None:
                        stabilize_ts = item.sample_timestamp or item.created_at
                else:
                    stable_hits = 0
            probes = _extract_probe_values(item.raw_payload.get('device_data') if isinstance(item.raw_payload, dict) else None)
            if not probes:
                probes = _extract_probe_values(item.raw_payload)
            probe_counts.append(len(probes))
            if current_temp is not None and probes:
                pit_probe_deltas.extend(abs(current_temp - probe) for probe in probes if probe > 0)
            if len(probes) == 0 and item.engaged:
                probe_failures += 1

        start_ts = first.sample_timestamp or first.created_at
        end_ts = last.sample_timestamp or last.created_at
        duration_seconds = int((end_ts - start_ts).total_seconds()) if start_ts and end_ts else 0
        disconnect_proxy = False
        if len(group) >= 2:
            max_gap = max(
                int(((group[idx].sample_timestamp or group[idx].created_at) - (group[idx - 1].sample_timestamp or group[idx - 1].created_at)).total_seconds())
                for idx in range(1, len(group))
                if (group[idx].sample_timestamp or group[idx].created_at) and (group[idx - 1].sample_timestamp or group[idx - 1].created_at)
            )
            disconnect_proxy = max_gap > gap_minutes * 60
        stabilized = stabilize_ts is not None
        completed = reached_target and stabilized and bool(last.engaged is False or duration_seconds >= 1800)
        session_success = reached_target and stabilized and not disconnect_proxy and errors == 0
        stability_score = max(0.0, min(1.0, 1 - (_percentile(temp_deltas, 0.5) or 0) / 50)) if temp_deltas and target_temp else (1.0 if reached_target else 0.0)
        overshoot_rate = 1.0 if overshoot else 0.0
        time_to_stabilize_seconds = int((stabilize_ts - start_ts).total_seconds()) if stabilize_ts and start_ts else None

        if disconnect_proxy:
            archetype = 'dropout'
            dropoff_reason = 'disconnect_proxy'
        elif overshoot and not stabilized:
            archetype = 'overshoot'
            dropoff_reason = 'overshoot_before_stable'
        elif reached_target and not stabilized:
            archetype = 'oscillation'
            dropoff_reason = 'never_stabilized'
        elif session_success:
            archetype = 'stable'
            dropoff_reason = 'completed'
        else:
            archetype = 'incomplete'
            dropoff_reason = 'never_reached_target' if not reached_target else 'ended_before_completion'

        sessions.append(DerivedSession(
            device_id=device_id,
            start_ts=start_ts,
            end_ts=end_ts,
            events=group,
            reached_target=reached_target,
            stabilized=stabilized,
            completed=completed,
            disconnect_proxy=disconnect_proxy,
            session_success=session_success,
            overshoot=overshoot,
            stability_score=round(stability_score, 3),
            overshoot_rate=overshoot_rate,
            time_to_stabilize_seconds=time_to_stabilize_seconds,
            avg_rssi=round(sum(rssis) / len(rssis), 1) if rssis else None,
            min_rssi=min(rssis) if rssis else None,
            firmware_version=last.firmware_version,
            grill_type=last.grill_type,
            target_temp=target_temp,
            error_count=errors,
            archetype=archetype,
            probe_count=max(probe_counts) if probe_counts else 0,
            probe_failure=probe_failures > 0 and max(probe_counts) == 0,
            avg_pit_probe_delta=round(sum(pit_probe_deltas) / len(pit_probe_deltas), 1) if pit_probe_deltas else None,
            dropoff_reason=dropoff_reason,
        ))
    return sessions


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
    for event in latest_rows or latest_by_device.values():
        device_id = event.device_id
        if event.engaged:
            engaged_latest_devices.add(device_id)
        if event.firmware_version:
            latest_firmware_by_device[device_id] = event.firmware_version
        if event.grill_type:
            latest_grill_type_by_device[device_id] = event.grill_type

    firmware = Counter(latest_firmware_by_device.values())
    grill_types = Counter(latest_grill_type_by_device.values())

    derived_sessions: list[DerivedSession] = []
    for device_id, events in device_buckets.items():
        derived_sessions.extend(_derive_sessions(device_id, events, gap_minutes=int(metadata.get('session_gap_timeout_minutes') or 45)))

    sessions_count = len(derived_sessions)
    reached_target_count = sum(1 for session in derived_sessions if session.reached_target)
    stabilized_count = sum(1 for session in derived_sessions if session.stabilized)
    completed_count = sum(1 for session in derived_sessions if session.completed)
    success_count = sum(1 for session in derived_sessions if session.session_success)
    overshoot_count = sum(1 for session in derived_sessions if session.overshoot)
    disconnect_count = sum(1 for session in derived_sessions if session.disconnect_proxy)
    stable_scores = [session.stability_score for session in derived_sessions]
    time_to_stabilize = [session.time_to_stabilize_seconds for session in derived_sessions if session.time_to_stabilize_seconds is not None]
    probe_sessions = [session for session in derived_sessions if session.probe_count > 0]
    probe_failure_sessions = [session for session in derived_sessions if session.probe_failure]
    pit_probe_deltas = [session.avg_pit_probe_delta for session in derived_sessions if session.avg_pit_probe_delta is not None]
    session_durations = [int((session.end_ts - session.start_ts).total_seconds()) for session in derived_sessions if session.start_ts and session.end_ts]
    current_rssis = [float(event.rssi) for event in (latest_rows or latest_by_device.values()) if event.rssi is not None]

    dropoff_counter = Counter(session.dropoff_reason for session in derived_sessions if session.dropoff_reason != 'completed')
    archetype_counter = Counter(session.archetype for session in derived_sessions)
    timeout_count = dropoff_counter.get('ended_before_completion', 0)
    oscillation_count = archetype_counter.get('oscillation', 0)

    temp_curve_buckets: dict[int, list[float]] = defaultdict(list)
    for session in derived_sessions:
        start_ts = session.start_ts
        for event in session.events:
            ts = event.sample_timestamp or event.created_at
            if ts is None or start_ts is None or event.current_temp is None or event.target_temp is None:
                continue
            minute_bucket = max(0, min(120, int((ts - start_ts).total_seconds() // 60)))
            temp_curve_buckets[minute_bucket].append(float(event.current_temp) - float(event.target_temp))

    curve = [
        {
            'minute_bucket': minute,
            'p50_temp_delta': _percentile(values, 0.5),
            'p90_temp_delta': _percentile(values, 0.9),
            'sessions': len(values),
        }
        for minute, values in sorted(temp_curve_buckets.items())[:30]
    ]

    connectivity_groups: dict[str, list[DerivedSession]] = defaultdict(list)
    for session in derived_sessions:
        connectivity_groups[_classify_rssi_bucket(session.avg_rssi if session.avg_rssi is not None else session.min_rssi)].append(session)

    connectivity_buckets = []
    for bucket in ['>-65 dBm', '-74 to -65 dBm', '-84 to -75 dBm', '<=-85 dBm', 'unknown']:
        rows = connectivity_groups.get(bucket, [])
        if not rows:
            continue
        connectivity_buckets.append({
            'bucket': bucket,
            'sessions': len(rows),
            'failure_rate': round(sum(1 for row in rows if not row.session_success) / len(rows), 3),
            'stability_score': round(sum(row.stability_score for row in rows) / len(rows), 3) if rows else None,
            'disconnect_rate': round(sum(1 for row in rows if row.disconnect_proxy) / len(rows), 3),
        })

    def _cohort_health(rows: list[DerivedSession], label: str) -> list[dict[str, Any]]:
        groups: dict[str, list[DerivedSession]] = defaultdict(list)
        for row in rows:
            key = row.firmware_version if label == 'firmware' else row.grill_type
            groups[key or 'unknown'].append(row)
        payload = []
        for key, items in groups.items():
            total = len(items)
            failure_rate = round(sum(1 for item in items if not item.session_success) / total, 3)
            disconnect_rate = round(sum(1 for item in items if item.disconnect_proxy) / total, 3)
            override_rate = 0.0
            health_score = round(max(0.0, 1.0 - (failure_rate * 0.5 + disconnect_rate * 0.3 + (1 - (sum(item.stability_score for item in items) / total)) * 0.2)), 3)
            severity = 'high' if failure_rate >= 0.35 else 'medium' if failure_rate >= 0.18 else 'low'
            payload.append({
                'key': key,
                'sessions': total,
                'disconnect_rate': disconnect_rate,
                'manual_override_rate': override_rate,
                'failure_rate': failure_rate,
                'health_score': health_score,
                'severity': severity,
            })
        return sorted(payload, key=lambda item: (item['severity'] == 'high', item['failure_rate'], item['sessions']), reverse=True)[:10]

    issue_insights: list[dict[str, Any]] = []
    worst_connectivity = max(connectivity_buckets, key=lambda row: row['failure_rate'], default=None)
    if worst_connectivity and worst_connectivity['sessions'] >= 3 and worst_connectivity['failure_rate'] >= 0.3:
        issue_insights.append({
            'issue': 'Connectivity-linked session failure',
            'signal': f"Failure rate is {round(worst_connectivity['failure_rate'] * 100)}% in RSSI bucket {worst_connectivity['bucket']}.",
            'cohort': worst_connectivity['bucket'],
            'confidence': 'medium' if worst_connectivity['sessions'] >= 10 else 'low',
            'action': 'Compare weak-signal cohorts against stronger-signal sessions and inspect disconnect-heavy sessions before product escalation.',
        })
    worst_fw = next((row for row in _cohort_health(derived_sessions, 'firmware') if row['sessions'] >= 3), None)
    if worst_fw and worst_fw['failure_rate'] >= 0.25:
        issue_insights.append({
            'issue': 'Firmware cohort underperforming',
            'signal': f"Firmware {worst_fw['key']} shows {round(worst_fw['failure_rate'] * 100)}% session failure across {worst_fw['sessions']} observed sessions.",
            'cohort': f"firmware:{worst_fw['key']}",
            'confidence': 'medium' if worst_fw['sessions'] >= 10 else 'low',
            'action': 'Inspect recent failed sessions for this firmware cohort and compare RSSI, overshoot, and stabilization behavior before assigning root cause.',
        })
    if overshoot_count >= 3 and sessions_count:
        issue_insights.append({
            'issue': 'Temperature control overshoot appearing in observed slice',
            'signal': f"Overshoot proxy appears in {round(overshoot_count / sessions_count * 100)}% of derived sessions.",
            'cohort': 'observed_slice',
            'confidence': 'medium' if sessions_count >= 10 else 'low',
            'action': 'Review target-vs-pit curve buckets and isolate overshoot sessions by model and firmware before tuning control logic.',
        })

    primary_active_devices_count = active_counts['15m'] or active_counts['5m'] or len(engaged_latest_devices)
    latest = {
        'business_date': newest.date().isoformat() if newest else None,
        'sessions': primary_active_devices_count,
        'connected_users': 0,
        'cook_success_rate': _safe_div(success_count, sessions_count or 1),
        'disconnect_rate': _safe_div(disconnect_count, sessions_count or 1),
        'temp_stability_score': round(sum(stable_scores) / len(stable_scores), 4) if stable_scores else 0.0,
        'avg_time_to_stabilization_seconds': int(sum(time_to_stabilize) / len(time_to_stabilize)) if time_to_stabilize else 0,
        'manual_override_rate': 0.0,
        'firmware_health_score': round(max(0.0, 1 - _safe_div(len(error_devices), distinct_devices or 1)), 4),
        'session_reliability_score': round(sum(1 for s in derived_sessions if s.session_success) / sessions_count, 4) if sessions_count else round(max(0.0, 1 - _safe_div(len(low_rssi_devices | error_devices), distinct_devices or 1)), 4),
        'error_rate': _safe_div(sum(1 for s in derived_sessions if s.error_count > 0), sessions_count or 1),
    }

    firmware_health = _cohort_health(derived_sessions, 'firmware') if derived_sessions else [
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
    ]
    grill_type_health = _cohort_health(derived_sessions, 'grill_type') if derived_sessions else [
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
    ]

    top_error_codes = Counter()
    for session in derived_sessions:
        for event in session.events:
            for code in event.error_codes_json or []:
                try:
                    if int(code) != 0:
                        top_error_codes[str(code)] += 1
                except (TypeError, ValueError):
                    continue

    return {
        'latest': latest,
        'daily': [latest] if latest.get('business_date') else [],
        'firmware_health': firmware_health,
        'grill_type_health': grill_type_health,
        'top_error_codes': [{'code': code, 'count': count} for code, count in top_error_codes.most_common(10)],
        'top_issue_patterns': [
            {'pattern': 'disconnect_proxy', 'count': disconnect_count},
            {'pattern': 'overshoot', 'count': overshoot_count},
            {'pattern': 'never_reached_target', 'count': dropoff_counter.get('never_reached_target', 0)},
            {'pattern': 'never_stabilized', 'count': dropoff_counter.get('never_stabilized', 0)},
        ],
        'slice_snapshot': {
            'distinct_devices_observed': distinct_devices,
            'engaged_latest_devices': len(engaged_latest_devices),
            'active_devices_last_5m': active_counts['5m'],
            'active_devices_last_15m': active_counts['15m'],
            'active_devices_last_60m': active_counts['60m'],
            'active_devices_last_24h': active_counts['24h'],
            'sessions_derived': sessions_count or primary_active_devices_count,
            'recent_activity_window_minutes': 15,
            'average_events_per_device_in_slice': round(sum(len(events) for events in device_buckets.values()) / max(len(device_buckets), 1), 2),
            'median_events_per_device_in_slice': median([len(events) for events in device_buckets.values()]) if device_buckets else 0,
            'average_session_duration_seconds': round(sum(int((session.end_ts - session.start_ts).total_seconds()) for session in derived_sessions if session.start_ts and session.end_ts) / max(sessions_count, 1), 2) if derived_sessions else 0,
            'median_session_duration_seconds': median([int((session.end_ts - session.start_ts).total_seconds()) for session in derived_sessions if session.start_ts and session.end_ts]) if derived_sessions else 0,
            'low_rssi_session_rate': _safe_div(sum(1 for session in derived_sessions if (session.min_rssi is not None and session.min_rssi <= -75)), sessions_count or 1),
            'error_vector_presence_rate': _safe_div(sum(1 for session in derived_sessions if session.error_count > 0), sessions_count or 1),
            'target_temp_distribution': [{'target_temp': key, 'count': count} for key, count in target_temps.most_common(10)],
        },
        'collection_metadata': {
            'source': 'sg_device_shadows_stream',
            'region': metadata.get('region'),
            'table': metadata.get('table'),
            'sample_source': 'dynamodb_stream',
            'records_loaded': len(stream_events),
            'sessions_derived': sessions_count or primary_active_devices_count,
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
            'coverage_summary': f'Observed {distinct_devices} devices and {sessions_count or primary_active_devices_count} derived sessions in the loaded stream slice; full-table counts show {active_counts["15m"]} devices active in the last 15 minutes, {active_counts["60m"]} in 60 minutes, and {len(engaged_latest_devices)} engaged on latest state across the last 24 hours.',
        },
        'confidence': {
            'global_completeness': 'estimated',
            'session_derivation': 'estimated',
            'disconnect_detection': 'proxy',
            'cook_success': 'estimated',
            'manual_override': 'unavailable',
            'reason': f'Live stream-backed telemetry is using raw stream rows plus derived session heuristics (target reached, stabilization bands, RSSI/dropout proxies). Suitable for observed-slice product analytics, but not a canonical fleet cook ledger.',
        },
        'analytics': {
            'cook_lifecycle_funnel': [
                {'step': 'started', 'sessions': sessions_count, 'rate': 1.0 if sessions_count else 0.0},
                {'step': 'reached_target', 'sessions': reached_target_count, 'rate': _safe_div(reached_target_count, sessions_count or 1)},
                {'step': 'stable', 'sessions': stabilized_count, 'rate': _safe_div(stabilized_count, sessions_count or 1)},
                {'step': 'completed', 'sessions': completed_count, 'rate': _safe_div(completed_count, sessions_count or 1)},
            ],
            'dropoff_reasons': [
                {'reason': key, 'sessions': count, 'rate': _safe_div(count, sessions_count or 1)}
                for key, count in dropoff_counter.most_common(5)
            ],
            'pit_temperature_curve': curve,
            'session_archetypes': [
                {
                    'archetype': key,
                    'sessions': count,
                    'rate': _safe_div(count, sessions_count or 1),
                    'description': {
                        'stable': 'Reached target and stabilized within the observed session heuristic.',
                        'overshoot': 'Exceeded target materially before stable convergence.',
                        'oscillation': 'Reached target range but failed to remain stable.',
                        'dropout': 'Session showed disconnect/gap proxy suggesting broken continuity.',
                        'incomplete': 'Session did not clearly reach target or completion.'
                    }.get(key, 'Derived telemetry archetype'),
                }
                for key, count in archetype_counter.most_common(5)
            ],
            'probe_usage': [
                {'probe_count': bucket, 'sessions': count, 'rate': _safe_div(count, sessions_count or 1)}
                for bucket, count in sorted(Counter(min(3, session.probe_count) for session in derived_sessions).items())
            ],
            'probe_failure_rate': _safe_div(len(probe_failure_sessions), sessions_count or 1) if derived_sessions else None,
            'pit_probe_delta_avg': round(sum(pit_probe_deltas) / len(pit_probe_deltas), 1) if pit_probe_deltas else None,
            'connectivity_buckets': connectivity_buckets,
            'issue_insights': issue_insights,
            'derived_metrics': {
                'stability_score': round(sum(stable_scores) / len(stable_scores), 3) if stable_scores else None,
                'overshoot_rate': _safe_div(overshoot_count, sessions_count or 1) if sessions_count else None,
                'oscillation_rate': _safe_div(oscillation_count, sessions_count or 1) if sessions_count else None,
                'timeout_rate': _safe_div(timeout_count, sessions_count or 1) if sessions_count else None,
                'time_to_stabilize_seconds': int(sum(time_to_stabilize) / len(time_to_stabilize)) if time_to_stabilize else None,
                'time_to_stabilize_p50_seconds': int(_percentile([float(value) for value in time_to_stabilize], 0.5) or 0) if time_to_stabilize else None,
                'time_to_stabilize_p95_seconds': int(_percentile([float(value) for value in time_to_stabilize], 0.95) or 0) if time_to_stabilize else None,
                'disconnect_proxy_rate': _safe_div(disconnect_count, sessions_count or 1) if sessions_count else None,
                'session_success_rate': _safe_div(success_count, sessions_count or 1) if sessions_count else None,
                'active_cooks_now': active_counts['15m'] or active_counts['5m'] or len(engaged_latest_devices),
                'cooks_started_24h': sessions_count,
                'cooks_completed_24h': completed_count,
                'median_cook_duration_seconds': int(_percentile([float(value) for value in session_durations], 0.5) or 0) if session_durations else None,
                'p95_cook_duration_seconds': int(_percentile([float(value) for value in session_durations], 0.95) or 0) if session_durations else None,
                'median_rssi_now': _percentile(current_rssis, 0.5) if current_rssis else None,
                'devices_reporting_last_5m': active_counts['5m'],
                'devices_reporting_last_15m': active_counts['15m'],
            },
        },
    }
