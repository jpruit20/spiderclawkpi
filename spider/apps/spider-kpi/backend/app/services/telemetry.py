from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from statistics import median
from typing import Any

from sqlalchemy import desc, inspect, select
from sqlalchemy.orm import Session

from app.models import SourceSyncRun, TelemetryDaily, TelemetrySession, TelemetryStreamEvent
from app.services.telemetry_history import get_telemetry_history_monthly
from app.services.telemetry_stream_summary import summarize_stream_telemetry


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _build_cook_analysis(db: Session, lookback_days: int = 30) -> dict[str, Any]:
    """Classify sessions by cook style, temperature range, and duration bucket.

    Cook styles:
      - startup_only: session < 15 minutes (user lit, got to temp, killed Venom)
      - hot_and_fast: target >= 400F (burgers, hot dogs, searing)
      - low_and_slow: target <= 275F AND session > 30 min (brisket, pulled pork, ribs)
      - medium_heat: target 276-399F (chicken, steaks, general grilling)
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(lookback_days, 1))
    sessions = db.execute(
        select(TelemetrySession).where(TelemetrySession.session_start >= cutoff)
    ).scalars().all()

    if not sessions:
        return {"total_sessions": 0, "cook_styles": {}, "temp_ranges": {}, "duration_ranges": {}, "style_details": {}}

    cook_styles: dict[str, int] = {"startup_only": 0, "hot_and_fast": 0, "low_and_slow": 0, "medium_heat": 0, "unclassified": 0}
    temp_ranges: dict[str, int] = {"under_250": 0, "250_to_300": 0, "300_to_400": 0, "over_400": 0}
    duration_ranges: dict[str, int] = {"under_30m": 0, "30m_to_2h": 0, "2h_to_4h": 0, "over_4h": 0}

    # Per-style aggregations for deeper analytics
    style_durations: dict[str, list[int]] = defaultdict(list)
    style_stability: dict[str, list[float]] = defaultdict(list)
    style_success: dict[str, list[bool]] = defaultdict(list)

    for s in sessions:
        dur = s.session_duration_seconds or 0
        temp = s.target_temp or 0

        # Duration buckets
        if dur < 1800:
            duration_ranges["under_30m"] += 1
        elif dur < 7200:
            duration_ranges["30m_to_2h"] += 1
        elif dur < 14400:
            duration_ranges["2h_to_4h"] += 1
        else:
            duration_ranges["over_4h"] += 1

        # Temperature buckets
        if temp <= 0:
            pass  # no target set
        elif temp < 250:
            temp_ranges["under_250"] += 1
        elif temp <= 300:
            temp_ranges["250_to_300"] += 1
        elif temp <= 400:
            temp_ranges["300_to_400"] += 1
        else:
            temp_ranges["over_400"] += 1

        # Cook style classification
        if dur < 900:  # <15 min
            style = "startup_only"
        elif temp >= 400:
            style = "hot_and_fast"
        elif temp <= 275 and dur >= 1800:
            style = "low_and_slow"
        elif temp > 0:
            style = "medium_heat"
        else:
            style = "unclassified"

        cook_styles[style] += 1
        style_durations[style].append(dur)
        if s.temp_stability_score is not None:
            style_stability[style].append(s.temp_stability_score)
        style_success[style].append(bool(s.cook_success))

    # Build per-style detail summaries
    style_details: dict[str, dict[str, Any]] = {}
    for style_name, count in cook_styles.items():
        if count == 0:
            continue
        durations = style_durations.get(style_name, [])
        stabilities = style_stability.get(style_name, [])
        successes = style_success.get(style_name, [])
        style_details[style_name] = {
            "count": count,
            "pct": round(count / len(sessions), 4),
            "avg_duration_seconds": round(sum(durations) / max(len(durations), 1)),
            "median_duration_seconds": round(median(durations)) if durations else 0,
            "avg_stability_score": round(sum(stabilities) / max(len(stabilities), 1), 3) if stabilities else None,
            "success_rate": round(sum(1 for s in successes if s) / max(len(successes), 1), 4) if successes else None,
        }

    return {
        "total_sessions": len(sessions),
        "cook_styles": cook_styles,
        "temp_ranges": temp_ranges,
        "duration_ranges": duration_ranges,
        "style_details": style_details,
    }


def _build_cook_analysis_from_derived(derived_sessions: list) -> dict[str, Any]:
    """Build cook_analysis from DerivedSession objects produced by stream summary.

    This replaces the TelemetrySession-based version when stream data is the
    primary source (which is the normal case — the telemetry_sessions table
    is only populated by the legacy materializer).
    """
    if not derived_sessions:
        return {"total_sessions": 0, "cook_styles": {}, "temp_ranges": {}, "duration_ranges": {}, "style_details": {}}

    cook_styles: dict[str, int] = {"startup_only": 0, "hot_and_fast": 0, "low_and_slow": 0, "medium_heat": 0, "unclassified": 0}
    temp_ranges: dict[str, int] = {"under_250": 0, "250_to_300": 0, "300_to_400": 0, "over_400": 0}
    duration_ranges: dict[str, int] = {"under_30m": 0, "30m_to_2h": 0, "2h_to_4h": 0, "over_4h": 0}
    style_durations: dict[str, list[int]] = defaultdict(list)
    style_stability: dict[str, list[float]] = defaultdict(list)
    style_success: dict[str, list[bool]] = defaultdict(list)

    for s in derived_sessions:
        start = s.start_ts
        end = s.end_ts
        dur = int((end - start).total_seconds()) if start and end else 0
        temp = s.target_temp or 0

        # Duration buckets
        if dur < 1800:
            duration_ranges["under_30m"] += 1
        elif dur < 7200:
            duration_ranges["30m_to_2h"] += 1
        elif dur < 14400:
            duration_ranges["2h_to_4h"] += 1
        else:
            duration_ranges["over_4h"] += 1

        # Temperature buckets
        if temp <= 0:
            pass
        elif temp < 250:
            temp_ranges["under_250"] += 1
        elif temp <= 300:
            temp_ranges["250_to_300"] += 1
        elif temp <= 400:
            temp_ranges["300_to_400"] += 1
        else:
            temp_ranges["over_400"] += 1

        # Cook style classification
        if dur < 900:
            style = "startup_only"
        elif temp >= 400:
            style = "hot_and_fast"
        elif temp <= 275 and dur >= 1800:
            style = "low_and_slow"
        elif temp > 0:
            style = "medium_heat"
        else:
            style = "unclassified"

        cook_styles[style] += 1
        style_durations[style].append(dur)
        if s.stability_score is not None:
            style_stability[style].append(s.stability_score)
        style_success[style].append(bool(s.session_success))

    style_details: dict[str, dict[str, Any]] = {}
    total = len(derived_sessions)
    for style_name, count in cook_styles.items():
        if count == 0:
            continue
        durations = style_durations.get(style_name, [])
        stabilities = style_stability.get(style_name, [])
        successes = style_success.get(style_name, [])
        style_details[style_name] = {
            "count": count,
            "pct": round(count / total, 4),
            "avg_duration_seconds": round(sum(durations) / max(len(durations), 1)),
            "median_duration_seconds": round(median(durations)) if durations else 0,
            "avg_stability_score": round(sum(stabilities) / max(len(stabilities), 1), 3) if stabilities else None,
            "success_rate": round(sum(1 for s in successes if s) / max(len(successes), 1), 4) if successes else None,
        }

    return {
        "total_sessions": total,
        "cook_styles": cook_styles,
        "temp_ranges": temp_ranges,
        "duration_ranges": duration_ranges,
        "style_details": style_details,
    }


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


def summarize_telemetry(db: Session, lookback_days: int = 30, include_cook_analysis: bool = False) -> dict[str, Any]:
    historical_monthly = get_telemetry_history_monthly(db)
    if telemetry_stream_table_available(db):
        fresh_stream_events = db.execute(
            select(TelemetryStreamEvent)
            .where(TelemetryStreamEvent.sample_timestamp >= datetime.now(timezone.utc) - timedelta(days=max(lookback_days, 1)))
            .order_by(desc(TelemetryStreamEvent.sample_timestamp))
            .limit(5000)
        ).scalars().all()
        if fresh_stream_events:
            payload = summarize_stream_telemetry(db, fresh_stream_events)
            payload.setdefault('analytics', {})['historical_monthly'] = historical_monthly
            payload.setdefault('collection_metadata', {})['historical_backfill_loaded'] = bool(historical_monthly)
            payload['collection_metadata']['historical_months_loaded'] = len(historical_monthly)
            # cook_analysis is now built inside summarize_stream_telemetry
            # directly from the derived sessions — no extra query needed.
            if not include_cook_analysis:
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
    distinct_engaged_devices = metadata.get('distinct_engaged_devices_observed') or 0
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
        "cook_analysis": _build_cook_analysis(db, lookback_days),
    }
