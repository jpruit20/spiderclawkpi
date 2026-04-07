from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import TelemetryDaily, TelemetrySession
from app.services.source_health import finish_sync_run, start_sync_run, upsert_source_config

settings = get_settings()
TIMEOUT_SECONDS = 60
SOURCE_NAME = "aws_telemetry"


def _configured() -> bool:
    return bool(settings.aws_telemetry_url or settings.aws_telemetry_local_path)


def _parse_datetime(value: Any) -> datetime | None:
    if value in {None, "", 0}:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _load_records() -> list[dict[str, Any]]:
    if settings.aws_telemetry_local_path:
        path = Path(settings.aws_telemetry_local_path)
        raw = path.read_text(encoding="utf-8")
    elif settings.aws_telemetry_url:
        headers = {"Accept": "application/json"}
        if settings.aws_telemetry_api_token:
            headers["Authorization"] = f"Bearer {settings.aws_telemetry_api_token}"
        response = requests.get(settings.aws_telemetry_url, headers=headers, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        raw = response.text
    else:
        return []

    stripped = raw.strip()
    if not stripped:
        return []
    if stripped.startswith("["):
        payload = json.loads(stripped)
        return [item for item in payload if isinstance(item, dict)]

    rows: list[dict[str, Any]] = []
    for line in stripped.splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = json.loads(line)
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _stability_score(actual_series: list[Any], target_temp: float | None) -> float:
    if not actual_series or not target_temp:
        return 0.0
    values = []
    for point in actual_series:
        if isinstance(point, dict):
            values.append(_as_float(point.get("temp") or point.get("value")))
        else:
            values.append(_as_float(point))
    if not values:
        return 0.0
    avg_abs_error = sum(abs(value - target_temp) for value in values) / max(len(values), 1)
    score = max(0.0, 1.0 - min(1.0, avg_abs_error / max(target_temp * 0.12, 15.0)))
    return round(score, 4)


def _time_to_stabilization(actual_series: list[Any], target_temp: float | None) -> int | None:
    if not actual_series or not target_temp:
        return None
    window = max(8.0, target_temp * 0.05)
    for idx, point in enumerate(actual_series):
        value = _as_float(point.get("temp") if isinstance(point, dict) else point)
        if abs(value - target_temp) <= window:
            return idx * 60
    return None


def _firmware_health_score(disconnect_events: int, error_count: int, stability_score: float) -> float:
    penalty = min(0.75, disconnect_events * 0.12 + error_count * 0.08 + max(0.0, 0.35 - stability_score))
    return round(max(0.0, 1.0 - penalty), 4)


def _session_reliability_score(disconnect_events: int, override_rate: float, firmware_health_score: float, cook_success: bool) -> float:
    score = firmware_health_score
    score -= min(0.4, disconnect_events * 0.1)
    score -= min(0.2, override_rate * 0.5)
    if not cook_success:
        score -= 0.15
    return round(max(0.0, min(1.0, score)), 4)


def _cook_success(stability_score: float, disconnect_events: int, error_count: int, session_duration_seconds: int | None) -> bool:
    duration_ok = (session_duration_seconds or 0) >= 1800
    return stability_score >= 0.72 and disconnect_events <= 1 and error_count == 0 and duration_ok


def sync_aws_telemetry(db: Session, max_records: int = 5000) -> dict[str, Any]:
    configured = _configured()
    upsert_source_config(
        db,
        SOURCE_NAME,
        configured=configured,
        sync_mode="pull",
        config_json={
            "source_type": "connector",
            "input": "url" if settings.aws_telemetry_url else "local_path" if settings.aws_telemetry_local_path else None,
        },
    )
    db.commit()

    if not configured:
        return {"ok": False, "skipped": True, "records_processed": 0, "message": "AWS telemetry source is not configured"}

    run = start_sync_run(db, SOURCE_NAME, "sync_telemetry", {"max_records": max_records})
    db.commit()

    try:
        records = _load_records()[:max_records]
        db.execute(delete(TelemetrySession))
        db.execute(delete(TelemetryDaily))
        db.flush()

        daily = defaultdict(lambda: {
            "sessions": 0,
            "users": set(),
            "cook_success": 0,
            "disconnect_sessions": 0,
            "stability_sum": 0.0,
            "stabilization_sum": 0.0,
            "stabilization_count": 0,
            "override_sum": 0.0,
            "firmware_sum": 0.0,
            "reliability_sum": 0.0,
            "error_sessions": 0,
        })

        processed = 0
        for idx, record in enumerate(records):
            session_start = _parse_datetime(record.get("session_start"))
            session_end = _parse_datetime(record.get("session_end"))
            target_temp = _as_float(record.get("target_temp"), 0.0) or None
            actual_series = _as_list(record.get("actual_temp_time_series"))
            fan_series = _as_list(record.get("fan_output_time_series"))
            disconnect_events = _as_int(record.get("disconnect_events"))
            manual_overrides = _as_int(record.get("manual_overrides"))
            error_codes = [str(item) for item in _as_list(record.get("error_flags") or record.get("error_codes")) if str(item).strip()]
            error_count = len(error_codes)
            session_duration_seconds = None
            if session_start and session_end:
                session_duration_seconds = max(0, int((session_end - session_start).total_seconds()))

            temp_stability_score = _stability_score(actual_series, target_temp)
            time_to_stabilization_seconds = _time_to_stabilization(actual_series, target_temp)
            manual_override_rate = round(manual_overrides / max(len(actual_series), 1), 4)
            firmware_health_score = _firmware_health_score(disconnect_events, error_count, temp_stability_score)
            cook_success = _cook_success(temp_stability_score, disconnect_events, error_count, session_duration_seconds)
            session_reliability_score = _session_reliability_score(disconnect_events, manual_override_rate, firmware_health_score, cook_success)

            source_event_id = str(record.get("source_event_id") or record.get("event_id") or record.get("session_id") or f"telemetry-{idx}")
            db.add(TelemetrySession(
                source_event_id=source_event_id,
                device_id=record.get("device_id"),
                user_id=record.get("user_id"),
                session_id=record.get("session_id"),
                grill_type=record.get("grill_type"),
                firmware_version=record.get("firmware_version"),
                target_temp=target_temp,
                session_start=session_start,
                session_end=session_end,
                session_duration_seconds=session_duration_seconds,
                disconnect_events=disconnect_events,
                manual_overrides=manual_overrides,
                error_count=error_count,
                error_codes_json=error_codes,
                actual_temp_time_series=actual_series,
                fan_output_time_series=fan_series,
                temp_stability_score=temp_stability_score,
                time_to_stabilization_seconds=time_to_stabilization_seconds,
                firmware_health_score=firmware_health_score,
                session_reliability_score=session_reliability_score,
                manual_override_rate=manual_override_rate,
                cook_success=cook_success,
                raw_payload=record,
            ))
            processed += 1

            if not session_start:
                continue
            bucket = daily[session_start.date()]
            bucket["sessions"] += 1
            if record.get("user_id"):
                bucket["users"].add(str(record.get("user_id")))
            if cook_success:
                bucket["cook_success"] += 1
            if disconnect_events > 0:
                bucket["disconnect_sessions"] += 1
            bucket["stability_sum"] += temp_stability_score
            if time_to_stabilization_seconds is not None:
                bucket["stabilization_sum"] += time_to_stabilization_seconds
                bucket["stabilization_count"] += 1
            bucket["override_sum"] += manual_override_rate
            bucket["firmware_sum"] += firmware_health_score
            bucket["reliability_sum"] += session_reliability_score
            if error_count > 0:
                bucket["error_sessions"] += 1

        for business_date, values in daily.items():
            sessions = values["sessions"]
            db.add(TelemetryDaily(
                business_date=business_date,
                sessions=sessions,
                connected_users=len(values["users"]),
                cook_success_rate=round(values["cook_success"] / max(sessions, 1), 4),
                disconnect_rate=round(values["disconnect_sessions"] / max(sessions, 1), 4),
                temp_stability_score=round(values["stability_sum"] / max(sessions, 1), 4),
                avg_time_to_stabilization_seconds=round(values["stabilization_sum"] / max(values["stabilization_count"], 1), 2),
                manual_override_rate=round(values["override_sum"] / max(sessions, 1), 4),
                firmware_health_score=round(values["firmware_sum"] / max(sessions, 1), 4),
                session_reliability_score=round(values["reliability_sum"] / max(sessions, 1), 4),
                error_rate=round(values["error_sessions"] / max(sessions, 1), 4),
            ))

        run.metadata_json = {
            **(run.metadata_json or {}),
            "records_loaded": processed,
            "days_materialized": len(daily),
            "sample_source": "url" if settings.aws_telemetry_url else "local_path",
        }
        finish_sync_run(db, run, status="success", records_processed=processed)
        db.commit()
        return {"ok": True, "records_processed": processed, "days_materialized": len(daily)}
    except Exception as exc:
        finish_sync_run(db, run, status="failed", error_message=str(exc))
        db.commit()
        return {"ok": False, "records_processed": 0, "message": str(exc)}
