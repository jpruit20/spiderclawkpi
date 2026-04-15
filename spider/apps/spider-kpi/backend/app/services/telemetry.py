from __future__ import annotations

import time
from collections import Counter, defaultdict
from datetime import date, datetime, timezone, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

BUSINESS_TZ = ZoneInfo("America/New_York")

from sqlalchemy import desc, inspect, select
from sqlalchemy.orm import Session

from app.models import SourceSyncRun, TelemetryDaily, TelemetryHistoryDaily, TelemetrySession, TelemetryStreamEvent
from app.services.telemetry_history import get_telemetry_history_monthly
from app.services.telemetry_stream_summary import summarize_stream_telemetry

# Cache summarize_telemetry for a short window. The underlying data is
# continuously updated by the DynamoDB-Streams -> Lambda pipeline, but
# dashboard freshness doesn't need second-level resolution. A 60-second
# TTL flattens bursts of parallel requests (page load fires many at once)
# and insulates us from any future slow-query regression on the 2M+ row
# telemetry_stream_events table.
_SUMMARY_TTL_SECONDS = 60
_summary_cache: dict[tuple, tuple[float, dict[str, Any]]] = {}
# Stream events are capped per query to protect the 2M+ row table. When a
# wide historical range is selected, the sample is the most-recent 5000
# events from the end of that range — enough for stable distributional
# metrics (RSSI percentiles, firmware mix, issue patterns) without
# scanning the full table.
_STREAM_SAMPLE_LIMIT = 5000


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _severity_from_rate(rate: float, high: float, medium: float) -> str:
    if rate >= high:
        return "high"
    if rate >= medium:
        return "medium"
    return "low"


def telemetry_tables_available(db: Session) -> bool:
    inspector = inspect(db.bind)
    return inspector.has_table('telemetry_daily') and inspector.has_table('telemetry_sessions')


def telemetry_stream_table_available(db: Session) -> bool:
    inspector = inspect(db.bind)
    return inspector.has_table('telemetry_stream_events')


def _empty_telemetry_payload() -> dict[str, Any]:
    return {
        "latest": None,
        "daily": [],
        "firmware_health": [],
        "grill_type_health": [],
        "top_error_codes": [],
        "top_issue_patterns": [],
        "analytics": {"historical_monthly": []},
    }


def summarize_telemetry(
    db: Session,
    lookback_days: int = 30,
    *,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    """Summarize telemetry over a date window.

    When *start* and *end* are both provided (dashboard date picker case),
    the stream-event sample is drawn from that closed interval in Eastern
    business time. Otherwise falls back to the trailing *lookback_days*
    window from now — backward compatible for callers that don't know about
    the range (SystemHealth, IssueRadar, etc.).
    """
    now_ts = time.monotonic()
    cache_key: tuple = ("range", start.isoformat(), end.isoformat()) if (start and end) else ("trailing", lookback_days)
    cached = _summary_cache.get(cache_key)
    if cached is not None and (now_ts - cached[0]) < _SUMMARY_TTL_SECONDS:
        return cached[1]
    result = _compute_summary(db, lookback_days, start=start, end=end)
    _summary_cache[cache_key] = (now_ts, result)
    return result


def _range_bounds_utc(start: date, end: date) -> tuple[datetime, datetime]:
    """Convert an Eastern-time inclusive date range to UTC datetime bounds."""
    start_local = datetime.combine(start, datetime.min.time(), tzinfo=BUSINESS_TZ)
    end_local = datetime.combine(end, datetime.max.time(), tzinfo=BUSINESS_TZ)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _historical_summary_from_daily(db: Session, start: date, end: date) -> dict[str, Any] | None:
    """Build a summary payload from telemetry_history_daily for a historical range.

    Used when the selected range falls outside telemetry_stream_events'
    rolling retention. Fields that can only be computed from raw events
    (top_error_codes, top_issue_patterns, stability percentiles) are left
    empty; distributional fields (firmware, grill model, RSSI, cook temp,
    reliability) are rebuilt from the daily rollup.
    """
    rows = db.execute(
        select(TelemetryHistoryDaily)
        .where(
            TelemetryHistoryDaily.business_date >= start,
            TelemetryHistoryDaily.business_date <= end,
        )
        .order_by(TelemetryHistoryDaily.business_date)
    ).scalars().all()
    if not rows:
        return None

    total_events = sum(r.total_events or 0 for r in rows)
    total_errors = sum(r.error_events or 0 for r in rows)
    total_sessions = sum(r.session_count or 0 for r in rows)
    total_successful = sum(r.successful_sessions or 0 for r in rows)
    active_devices_sum = sum(r.active_devices or 0 for r in rows)
    engaged_sum = sum(r.engaged_devices or 0 for r in rows)

    # Event-weighted averages across the range
    rssi_weight_sum = sum((r.avg_rssi or 0) * (r.total_events or 0) for r in rows if r.avg_rssi is not None)
    rssi_weight_total = sum(r.total_events or 0 for r in rows if r.avg_rssi is not None)
    avg_rssi = (rssi_weight_sum / rssi_weight_total) if rssi_weight_total > 0 else None

    # Aggregate firmware/model distributions across the range
    firmware_totals: Counter = Counter()
    model_totals: Counter = Counter()
    for r in rows:
        for fw, count in (r.firmware_distribution or {}).items():
            firmware_totals[fw] += int(count or 0)
        for model, count in (r.model_distribution or {}).items():
            model_totals[model] += int(count or 0)

    # Session-weighted stability & success from cook_style_details_json
    stab_weight_sum = 0.0
    stab_weight_total = 0
    success_weight_sum = 0.0
    success_weight_total = 0
    for r in rows:
        details = r.cook_style_details_json or {}
        for style_info in details.values():
            count = int(style_info.get('count', 0) or 0)
            if count <= 0:
                continue
            stab = style_info.get('avg_stability_score')
            if stab is not None:
                stab_weight_sum += float(stab) * count
                stab_weight_total += count
            sr = style_info.get('success_rate')
            if sr is not None:
                success_weight_sum += float(sr) * count
                success_weight_total += count
    stability_score = (stab_weight_sum / stab_weight_total) if stab_weight_total > 0 else None
    style_success_rate = (success_weight_sum / success_weight_total) if success_weight_total > 0 else None
    overall_success_rate = _safe_div(total_successful, total_sessions) if total_sessions else style_success_rate

    firmware_health = [
        {
            'slug': _slugify_firmware(fw),
            'key': fw,
            'label': fw,
            'sessions': count,
            'reliability': None,
            'confidence': 'low',
        }
        for fw, count in firmware_totals.most_common(10)
    ]
    grill_type_health = [
        {
            'slug': _slugify_firmware(model),
            'key': model,
            'label': model,
            'sessions': count,
            'reliability': None,
            'confidence': 'low',
        }
        for model, count in model_totals.most_common(10)
    ]

    return {
        'latest': None,
        'daily': [],
        'firmware_health': firmware_health,
        'grill_type_health': grill_type_health,
        'top_error_codes': [],
        'top_issue_patterns': [],
        'slice_snapshot': {
            'distinct_devices_observed': max((r.active_devices or 0) for r in rows) if rows else 0,
            'engaged_latest_devices': rows[-1].engaged_devices or 0 if rows else 0,
            'active_devices_last_5m': 0,
            'active_devices_last_15m': 0,
            'active_devices_last_60m': 0,
            'active_devices_last_24h': rows[-1].active_devices or 0 if rows else 0,
            'sessions_derived': total_sessions,
            'recent_activity_window_minutes': 0,
        },
        'collection_metadata': {
            'source': 'telemetry_history_daily',
            'sample_source': 'historical_rollup',
            'records_loaded': len(rows),
            'sessions_derived': total_sessions,
            'days_materialized': len(rows),
            'distinct_devices_observed': max((r.active_devices or 0) for r in rows) if rows else 0,
            'engaged_latest_devices': rows[-1].engaged_devices or 0 if rows else 0,
            'active_devices_last_5m': 0,
            'active_devices_last_15m': 0,
            'active_devices_last_60m': 0,
            'active_devices_last_24h': rows[-1].active_devices or 0 if rows else 0,
            'oldest_sample_timestamp_seen': rows[0].business_date.isoformat() if rows else None,
            'newest_sample_timestamp_seen': rows[-1].business_date.isoformat() if rows else None,
            'max_record_cap_hit': False,
            'scan_truncated': False,
            'coverage_summary': (
                f'Historical rollup from telemetry_history_daily across {len(rows)} day(s). '
                f'Event-level series (top error codes, issue patterns) not available outside '
                f'the 7-day stream retention window.'
            ),
        },
        'confidence': {
            'global_completeness': 'estimated',
            'session_derivation': 'estimated',
            'disconnect_detection': 'unavailable',
            'cook_success': 'estimated',
            'manual_override': 'unavailable',
            'reason': 'Historical daily rollup only — raw event-level detail is outside the stream retention window.',
        },
        'analytics': {
            'cook_lifecycle_funnel': [],
            'dropoff_reasons': [],
            'pit_temperature_curve': [],
            'session_archetypes': [],
            'probe_usage': [],
            'probe_failure_rate': None,
            'pit_probe_delta_avg': None,
            'connectivity_buckets': [],
            'issue_insights': [],
            'derived_metrics': {
                'stability_score': round(stability_score, 3) if stability_score is not None else None,
                'overshoot_rate': None,
                'oscillation_rate': None,
                'timeout_rate': None,
                'time_to_stabilize_seconds': None,
                'time_to_stabilize_p50_seconds': None,
                'time_to_stabilize_p95_seconds': None,
                'disconnect_proxy_rate': None,
                'session_success_rate': round(overall_success_rate, 4) if overall_success_rate is not None else None,
                'active_cooks_now': 0,
                'cooks_started_24h': total_sessions,
                'cooks_completed_24h': total_successful,
                'median_cook_duration_seconds': None,
                'p95_cook_duration_seconds': None,
                'median_rssi_now': round(avg_rssi, 1) if avg_rssi is not None else None,
                'devices_reporting_last_5m': 0,
                'devices_reporting_last_15m': 0,
                'total_events_in_range': total_events,
                'total_errors_in_range': total_errors,
                'error_rate_in_range': _safe_div(total_errors, total_events) if total_events else None,
                'avg_active_devices_per_day': round(active_devices_sum / len(rows), 1) if rows else 0,
                'avg_engaged_devices_per_day': round(engaged_sum / len(rows), 1) if rows else 0,
            },
        },
    }


def _slugify_firmware(value: str) -> str:
    return ''.join(ch.lower() if ch.isalnum() else '-' for ch in str(value)).strip('-') or 'unknown'


def _compute_summary(
    db: Session,
    lookback_days: int,
    *,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    historical_monthly = get_telemetry_history_monthly(db)
    if telemetry_stream_table_available(db):
        stream_query = select(TelemetryStreamEvent).order_by(desc(TelemetryStreamEvent.sample_timestamp)).limit(_STREAM_SAMPLE_LIMIT)
        if start is not None and end is not None:
            start_utc, end_utc = _range_bounds_utc(start, end)
            stream_query = stream_query.where(
                TelemetryStreamEvent.sample_timestamp >= start_utc,
                TelemetryStreamEvent.sample_timestamp <= end_utc,
            )
        else:
            stream_query = stream_query.where(
                TelemetryStreamEvent.sample_timestamp >= datetime.now(timezone.utc) - timedelta(days=max(lookback_days, 1))
            )
        fresh_stream_events = db.execute(stream_query).scalars().all()
        if fresh_stream_events:
            payload = summarize_stream_telemetry(db, fresh_stream_events)
            payload.setdefault('analytics', {})['historical_monthly'] = historical_monthly
            payload.setdefault('collection_metadata', {})['historical_backfill_loaded'] = bool(historical_monthly)
            payload['collection_metadata']['historical_months_loaded'] = len(historical_monthly)
            payload['collection_metadata']['data_scope'] = 'live_stream'
            # Cook analysis is now served by GET /api/telemetry/cook-analysis
            # from pre-materialized daily data.
            payload['cook_analysis'] = None
            return payload

        # Historical-only range: stream events only retain ~6 days, so fall
        # back to telemetry_history_daily (836+ days of pre-rolled data) and
        # rebuild the same payload shape. Fields that require raw events
        # (top_error_codes, top_issue_patterns) are left empty.
        if start is not None and end is not None:
            payload = _historical_summary_from_daily(db, start, end)
            if payload is not None:
                payload.setdefault('analytics', {})['historical_monthly'] = historical_monthly
                payload.setdefault('collection_metadata', {})['historical_backfill_loaded'] = bool(historical_monthly)
                payload['collection_metadata']['historical_months_loaded'] = len(historical_monthly)
                payload['collection_metadata']['data_scope'] = 'historical_daily'
                payload['cook_analysis'] = None
                return payload

    if not telemetry_tables_available(db):
        return _empty_telemetry_payload()

    rows = db.execute(
        select(TelemetryDaily)
        .order_by(desc(TelemetryDaily.business_date))
        .limit(max(lookback_days, 1))
    ).scalars().all()
    if not rows:
        return _empty_telemetry_payload()

    latest = rows[0]
    sessions = db.execute(
        select(TelemetrySession)
        .order_by(desc(TelemetrySession.session_start))
        .limit(5000)
    ).scalars().all()

    firmware = defaultdict(lambda: {"sessions": 0, "disconnects": 0, "overrides": 0, "failures": 0})
    grill_types = defaultdict(lambda: {"sessions": 0, "disconnects": 0, "overrides": 0, "failures": 0})
    error_codes: Counter[str] = Counter()
    issue_patterns: Counter[str] = Counter()
    session_durations: list[int] = []
    target_temp_counter: Counter[str] = Counter()
    low_rssi_sessions = 0
    error_sessions = 0

    for item in sessions:
        fw = item.firmware_version or "unknown"
        gt = item.grill_type or "unknown"
        firmware[fw]["sessions"] += 1
        grill_types[gt]["sessions"] += 1
        firmware[fw]["disconnects"] += item.disconnect_events or 0
        grill_types[gt]["disconnects"] += item.disconnect_events or 0
        firmware[fw]["overrides"] += item.manual_overrides or 0
        grill_types[gt]["overrides"] += item.manual_overrides or 0
        if not item.cook_success:
            firmware[fw]["failures"] += 1
            grill_types[gt]["failures"] += 1
        session_durations.append(int(item.session_duration_seconds or 0))
        if item.target_temp is not None:
            target_temp_counter[str(int(item.target_temp))] += 1
        if ((item.raw_payload or {}).get('rssi_min') or 0) <= -75:
            low_rssi_sessions += 1
        if (item.error_count or 0) > 0:
            error_sessions += 1
        for code in item.error_codes_json or []:
            error_codes[str(code)] += 1
        if (item.disconnect_events or 0) > 0:
            issue_patterns["disconnect_cluster"] += 1
        if (item.temp_stability_score or 1.0) < 0.68:
            issue_patterns["temp_instability"] += 1
        if (item.manual_override_rate or 0.0) >= 0.2:
            issue_patterns["high_manual_override"] += 1
        if (item.firmware_health_score or 1.0) < 0.8:
            issue_patterns["firmware_health_drop"] += 1

    def _health_payload(rows_map: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
        payload = []
        for key, values in rows_map.items():
            total = values["sessions"]
            disconnect_rate = _safe_div(values["disconnects"], total)
            override_rate = _safe_div(values["overrides"], total)
            failure_rate = _safe_div(values["failures"], total)
            health_score = round(max(0.0, 1.0 - (disconnect_rate * 0.35 + override_rate * 0.2 + failure_rate * 0.45)), 3)
            payload.append({
                "key": key,
                "sessions": total,
                "disconnect_rate": round(disconnect_rate, 3),
                "manual_override_rate": round(override_rate, 3),
                "failure_rate": round(failure_rate, 3),
                "health_score": health_score,
                "severity": _severity_from_rate(1.0 - health_score, 0.35, 0.18),
            })
        return sorted(payload, key=lambda item: (item["severity"] == "high", item["health_score"], -item["sessions"]), reverse=True)

    latest_run = db.execute(
        select(SourceSyncRun)
        .where(SourceSyncRun.source_name == 'aws_telemetry', SourceSyncRun.status == 'success')
        .order_by(desc(SourceSyncRun.started_at))
        .limit(1)
    ).scalars().first()
    metadata = latest_run.metadata_json if latest_run else {}
    max_record_cap_hit = bool(metadata.get('max_record_cap_hit'))
    scan_truncated = bool(metadata.get('scan_truncated'))
    distinct_devices = metadata.get('distinct_devices_observed') or 0
    confidence = {
        "global_completeness": "proxy" if (max_record_cap_hit or scan_truncated or distinct_devices <= 1) else "estimated",
        "session_derivation": "estimated",
        "disconnect_detection": "proxy",
        "cook_success": "estimated",
        "manual_override": "unavailable" if all((item.manual_overrides or 0) == 0 for item in sessions) else "proxy",
        "reason": metadata.get('coverage_summary') or "Direct DynamoDB reads from sg_device_shadows are bounded and device-keyed; fleet-wide recency is not globally indexed.",
    }
    slice_snapshot = {
        "distinct_devices_observed": metadata.get('distinct_devices_observed') or 0,
        "distinct_engaged_devices_observed": metadata.get('distinct_engaged_devices_observed') or 0,
        "sessions_derived": metadata.get('sessions_derived') or len(sessions),
        "average_session_duration_seconds": round(sum(session_durations) / max(len(session_durations), 1), 2),
        "median_session_duration_seconds": median(session_durations) if session_durations else 0,
        "low_rssi_session_rate": round(_safe_div(low_rssi_sessions, len(sessions)), 4),
        "error_vector_presence_rate": round(_safe_div(error_sessions, len(sessions)), 4),
        "target_temp_distribution": [{"target_temp": key, "count": count} for key, count in target_temp_counter.most_common(10)],
    }

    return {
        "latest": {
            "business_date": latest.business_date,
            "sessions": latest.sessions,
            "connected_users": latest.connected_users,
            "cook_success_rate": latest.cook_success_rate,
            "disconnect_rate": latest.disconnect_rate,
            "temp_stability_score": latest.temp_stability_score,
            "avg_time_to_stabilization_seconds": latest.avg_time_to_stabilization_seconds,
            "manual_override_rate": latest.manual_override_rate,
            "firmware_health_score": latest.firmware_health_score,
            "session_reliability_score": latest.session_reliability_score,
            "error_rate": latest.error_rate,
        },
        "daily": [
            {
                "business_date": row.business_date,
                "sessions": row.sessions,
                "connected_users": row.connected_users,
                "cook_success_rate": row.cook_success_rate,
                "disconnect_rate": row.disconnect_rate,
                "temp_stability_score": row.temp_stability_score,
                "avg_time_to_stabilization_seconds": row.avg_time_to_stabilization_seconds,
                "manual_override_rate": row.manual_override_rate,
                "firmware_health_score": row.firmware_health_score,
                "session_reliability_score": row.session_reliability_score,
                "error_rate": row.error_rate,
            }
            for row in reversed(rows)
        ],
        "firmware_health": _health_payload(firmware)[:10],
        "grill_type_health": _health_payload(grill_types)[:10],
        "top_error_codes": [{"code": code, "count": count} for code, count in error_codes.most_common(10)],
        "top_issue_patterns": [{"pattern": key, "count": count} for key, count in issue_patterns.most_common(10)],
        "slice_snapshot": slice_snapshot,
        "collection_metadata": {
            "source": "sg_device_shadows",
            "region": metadata.get('region'),
            "table": metadata.get('table'),
            "sample_source": metadata.get('sample_source'),
            "records_loaded": metadata.get('records_loaded'),
            "sessions_derived": metadata.get('sessions_derived'),
            "days_materialized": metadata.get('days_materialized'),
            "max_records": metadata.get('max_records'),
            "devices_observed": metadata.get('devices_observed'),
            "distinct_devices_observed": metadata.get('distinct_devices_observed'),
            "distinct_engaged_devices_observed": metadata.get('distinct_engaged_devices_observed'),
            "oldest_sample_timestamp_seen": metadata.get('oldest_sample_timestamp_seen'),
            "newest_sample_timestamp_seen": metadata.get('newest_sample_timestamp_seen'),
            "samples_retained": metadata.get('samples_retained'),
            "excluded_records": metadata.get('excluded_records'),
            "excluded_breakdown": metadata.get('excluded_breakdown'),
            "invalid_records": metadata.get('invalid_records'),
            "duplicate_samples": metadata.get('duplicate_samples'),
            "per_device_sample_count_distribution": metadata.get('per_device_sample_count_distribution'),
            "sessions_merged_away": metadata.get('sessions_merged_away'),
            "short_sessions_filtered": metadata.get('short_sessions_filtered'),
            "pages_scanned": metadata.get('pages_scanned'),
            "scan_truncated": metadata.get('scan_truncated'),
            "raw_rows_scanned": metadata.get('raw_rows_scanned'),
            "recent_rows_after_cutoff": metadata.get('recent_rows_after_cutoff'),
            "max_record_cap_hit": metadata.get('max_record_cap_hit'),
            "max_records_per_sync": metadata.get('max_records_per_sync'),
            "target_devices_per_sync": metadata.get('target_devices_per_sync'),
            "max_pages_scanned": metadata.get('max_pages_scanned'),
            "estimated_device_diversity_score": metadata.get('estimated_device_diversity_score'),
            "coverage_improvement_vs_last_run": metadata.get('coverage_improvement_vs_last_run'),
            "rolling_window_observed_devices": metadata.get('rolling_window_observed_devices'),
            "session_gap_timeout_minutes": metadata.get('session_gap_timeout_minutes'),
            "coverage_summary": metadata.get('coverage_summary'),
        },
        "confidence": confidence,
        "analytics": {
            "historical_monthly": historical_monthly,
        },
        "cook_analysis": None,
    }
