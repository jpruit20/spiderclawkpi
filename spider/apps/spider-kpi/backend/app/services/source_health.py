import time
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import desc, distinct, func, select
from sqlalchemy.orm import Session

from app.models import Alert, SourceConfig, SourceSyncRun, TelemetryStreamEvent

# Stream health details run six aggregates over the 2M+ row
# telemetry_stream_events table. Safety-net TTL cache keeps a burst of
# page-load requests from each re-running them.
_STREAM_HEALTH_TTL_SECONDS = 60
_stream_health_cache: dict[str, Any] = {"at": 0.0, "value": None}


STALE_MINUTES_BY_SOURCE = {
    "shopify": 90,
    "triplewhale": 180,
    "ga4": 240,
    "clarity": 240,
    "freshdesk": 360,
    "aws_telemetry": 360,
    "aws_telemetry_stream": 30,
    "decision-engine": 180,
    # Klaviyo + SharePoint poll once per day on the scheduler — give them
    # a 36h freshness threshold so a single missed run doesn't page.
    "klaviyo": 2160,
    "sharepoint": 2160,
    "shipstation": 360,
}
SOURCE_TYPES = {
    "shopify": "connector",
    "triplewhale": "connector",
    "ga4": "connector",
    "clarity": "connector",
    "freshdesk": "connector",
    "aws_telemetry": "connector",
    "aws_telemetry_stream": "connector",
    "klaviyo": "connector",
    "sharepoint": "connector",
    "shipstation": "connector",
    "decision-engine": "compute",
}


def upsert_source_config(
    db: Session,
    source_name: str,
    *,
    configured: bool,
    enabled: bool = True,
    sync_mode: str = "poll",
    config_json: dict[str, Any] | None = None,
) -> SourceConfig:
    config = db.execute(
        select(SourceConfig).where(SourceConfig.source_name == source_name)
    ).scalar_one_or_none()

    merged_config = {"source_type": SOURCE_TYPES.get(source_name, "connector")}
    if config_json:
        merged_config.update(config_json)

    if config is None:
        config = SourceConfig(
            source_name=source_name,
            configured=configured,
            enabled=enabled,
            sync_mode=sync_mode,
            config_json=merged_config,
        )
        db.add(config)
    else:
        config.configured = configured
        config.enabled = enabled
        config.sync_mode = sync_mode
        existing = config.config_json or {}
        existing.update(merged_config)
        config.config_json = existing

    db.flush()
    return config


def start_sync_run(db: Session, source_name: str, sync_type: str, metadata_json: dict[str, Any] | None = None) -> SourceSyncRun:
    existing_running = db.execute(
        select(SourceSyncRun)
        .where(SourceSyncRun.source_name == source_name, SourceSyncRun.status == "running")
        .order_by(desc(SourceSyncRun.started_at))
        .limit(1)
    ).scalars().first()
    if existing_running is not None:
        started_at = existing_running.started_at or existing_running.created_at
        if started_at and started_at < datetime.now(timezone.utc) - timedelta(minutes=30):
            existing_running.status = "failed"
            existing_running.finished_at = datetime.now(timezone.utc)
            existing_running.error_message = "Stale running sync expired automatically before starting a fresh run."
            existing_running.metadata_json = {
                **(existing_running.metadata_json or {}),
                "auto_expired": True,
                "expired_at": datetime.now(timezone.utc).isoformat(),
            }
            db.add(existing_running)
            db.flush()
        else:
            return existing_running

    run = SourceSyncRun(
        source_name=source_name,
        sync_type=sync_type,
        status="running",
        started_at=datetime.now(timezone.utc),
        metadata_json=metadata_json or {},
    )
    db.add(run)
    db.flush()
    return run


def finish_sync_run(
    db: Session,
    run: SourceSyncRun,
    *,
    status: str,
    records_processed: int = 0,
    error_message: str | None = None,
) -> SourceSyncRun:
    run.status = status
    run.records_processed = records_processed
    run.error_message = error_message
    run.finished_at = datetime.now(timezone.utc)

    config = db.execute(
        select(SourceConfig).where(SourceConfig.source_name == run.source_name)
    ).scalar_one_or_none()
    if config is None:
        config = SourceConfig(source_name=run.source_name, configured=False, config_json={"source_type": SOURCE_TYPES.get(run.source_name, "connector")})
        db.add(config)

    if status == "success":
        config.last_success_at = run.finished_at
        config.last_error = None
    else:
        config.last_failure_at = run.finished_at
        config.last_error = error_message

    db.flush()
    return run


def _staleness_minutes(source: str, latest_success_at: datetime | None) -> int | None:
    if latest_success_at is None:
        return None
    now = datetime.now(timezone.utc)
    return int((now - latest_success_at).total_seconds() // 60)


def _derived_status(config: SourceConfig, latest_run: SourceSyncRun | None) -> tuple[str, str, int | None]:
    if not config.enabled:
        return "disabled", "Source is disabled.", None
    if not config.configured:
        return "not_configured", "Required credentials or config are missing.", None
    if latest_run is None:
        return "never_run", "Source is configured but has never completed a sync.", None
    if latest_run.status == "running":
        return "running", "Sync is currently in progress.", None
    if latest_run.status == "failed":
        if latest_run.error_message and '429' in latest_run.error_message and config.last_success_at is not None:
            stale_minutes = _staleness_minutes(config.source_name, config.last_success_at)
            return "degraded", f"Latest poll was rate-limited (429). Using last successful sync from {stale_minutes} minutes ago with reduced confidence.", stale_minutes
        return "failed", latest_run.error_message or "Latest sync failed.", None

    stale_minutes = _staleness_minutes(config.source_name, config.last_success_at)
    threshold = STALE_MINUTES_BY_SOURCE.get(config.source_name, 240)
    if stale_minutes is not None and stale_minutes > threshold:
        return "stale", f"Latest successful sync is stale ({stale_minutes} minutes old).", stale_minutes
    return "healthy", "Latest sync succeeded and freshness is within threshold.", stale_minutes


def _upsert_source_alert(db: Session, config: SourceConfig, severity: str, title: str, message: str, status: str) -> None:
    if config.config_json.get("source_type") == "compute" and status == "healthy":
        return

    existing = db.execute(
        select(Alert).where(
            Alert.source == f"source-health:{config.source_name}",
            Alert.status == "open",
            Alert.title == title,
        )
    ).scalars().first()

    if status == "healthy":
        for open_alert in db.execute(
            select(Alert).where(
                Alert.source == f"source-health:{config.source_name}",
                Alert.status == "open",
            )
        ).scalars().all():
            open_alert.status = "resolved"
        return

    if existing is None:
        db.add(
            Alert(
                source=f"source-health:{config.source_name}",
                severity=severity,
                status="open",
                title=title,
                message=message,
                owner_team="Data Platform",
                confidence=0.98,
                metadata_json={"source_name": config.source_name, "source_type": config.config_json.get("source_type", "connector")},
            )
        )
    else:
        existing.severity = severity
        existing.message = message
        existing.owner_team = "Data Platform"
        existing.confidence = 0.98


def refresh_source_health_alerts(db: Session) -> None:
    configs = db.execute(select(SourceConfig)).scalars().all()
    for config in configs:
        latest_run = db.execute(
            select(SourceSyncRun)
            .where(SourceSyncRun.source_name == config.source_name)
            .order_by(desc(SourceSyncRun.started_at))
            .limit(1)
        ).scalar_one_or_none()
        status, summary, stale_minutes = _derived_status(config, latest_run)
        if status == "healthy":
            _upsert_source_alert(db, config, "low", "Source healthy", summary, status)
        elif status in {"failed", "stale", "degraded"}:
            severity = "high" if status == "failed" else "medium"
            title = "Source sync failed" if status == "failed" else "Source rate-limited" if status == "degraded" else "Source sync stale"
            if stale_minutes is not None and status == "stale":
                summary = f"{summary} Check scheduler, credentials, and upstream API health."
            _upsert_source_alert(db, config, severity, title, summary, status)
        else:
            severity = "medium" if status == "not_configured" else "low"
            title = "Source needs setup" if status == "not_configured" else "Source awaiting first successful run"
            _upsert_source_alert(db, config, severity, title, summary, status)
    db.flush()


def _stream_health_details(db: Session) -> dict[str, Any]:
    now_ts = time.monotonic()
    cached_value = _stream_health_cache["value"]
    if cached_value is not None and (now_ts - _stream_health_cache["at"]) < _STREAM_HEALTH_TTL_SECONDS:
        return cached_value
    value = _compute_stream_health_details(db)
    _stream_health_cache["at"] = now_ts
    _stream_health_cache["value"] = value
    return value


def _compute_stream_health_details(db: Session) -> dict[str, Any]:
    latest_sample = db.execute(
        select(TelemetryStreamEvent.sample_timestamp)
        .where(TelemetryStreamEvent.sample_timestamp.is_not(None))
        .order_by(desc(TelemetryStreamEvent.sample_timestamp))
        .limit(1)
    ).scalar_one_or_none()
    latest_created = db.execute(
        select(TelemetryStreamEvent.created_at)
        .order_by(desc(TelemetryStreamEvent.created_at))
        .limit(1)
    ).scalar_one_or_none()

    def _count_rows_since(delta: timedelta) -> int:
        cutoff = datetime.now(timezone.utc) - delta
        return int(db.execute(
            select(func.count()).select_from(TelemetryStreamEvent).where(TelemetryStreamEvent.created_at >= cutoff)
        ).scalar() or 0)

    def _count_devices_since(delta: timedelta) -> int:
        cutoff = datetime.now(timezone.utc) - delta
        return int(db.execute(
            select(func.count(distinct(TelemetryStreamEvent.device_id))).where(TelemetryStreamEvent.created_at >= cutoff)
        ).scalar() or 0)

    freshness_age_minutes = None
    reference_ts = latest_sample or latest_created
    if reference_ts is not None:
        freshness_age_minutes = int((datetime.now(timezone.utc) - reference_ts).total_seconds() // 60)

    details = {
        "latest_sample_timestamp": latest_sample,
        "latest_row_created_at": latest_created,
        "latest_stream_row_age_minutes": freshness_age_minutes,
        "rows_inserted_last_15m": _count_rows_since(timedelta(minutes=15)),
        "rows_inserted_last_60m": _count_rows_since(timedelta(minutes=60)),
        "rows_inserted_last_24h": _count_rows_since(timedelta(hours=24)),
        "distinct_devices_seen_last_15m": _count_devices_since(timedelta(minutes=15)),
        "distinct_devices_seen_last_60m": _count_devices_since(timedelta(minutes=60)),
        "distinct_devices_seen_last_24h": _count_devices_since(timedelta(hours=24)),
    }
    details["landed_row_growth_ok"] = bool(details["rows_inserted_last_60m"] > 0)
    details["lambda_processing_health"] = "healthy" if (freshness_age_minutes is not None and freshness_age_minutes <= 30 and details["rows_inserted_last_60m"] > 0) else "stale"
    details["ingest_endpoint_health"] = "healthy" if details["rows_inserted_last_15m"] > 0 else "idle"
    return details


def get_source_health(db: Session) -> list[dict[str, Any]]:
    configs = db.execute(select(SourceConfig).order_by(SourceConfig.source_name)).scalars().all()
    rows: list[dict[str, Any]] = []
    for config in configs:
        latest_run = db.execute(
            select(SourceSyncRun)
            .where(SourceSyncRun.source_name == config.source_name)
            .order_by(desc(SourceSyncRun.started_at))
            .limit(1)
        ).scalar_one_or_none()
        derived_status, status_summary, stale_minutes = _derived_status(config, latest_run)
        details_json = dict(config.config_json or {})
        if latest_run and latest_run.metadata_json:
            details_json["latest_run_metadata"] = latest_run.metadata_json
        if config.source_name == "aws_telemetry_stream":
            details_json.update(_stream_health_details(db))
        rows.append(
            {
                "source": config.source_name,
                "source_type": config.config_json.get("source_type", SOURCE_TYPES.get(config.source_name, "connector")),
                "configured": config.configured,
                "enabled": config.enabled,
                "sync_mode": config.sync_mode,
                "last_success_at": config.last_success_at,
                "last_failure_at": config.last_failure_at,
                "last_error": config.last_error,
                "latest_run_status": latest_run.status if latest_run else "never-run",
                "latest_run_started_at": latest_run.started_at if latest_run else None,
                "latest_run_finished_at": latest_run.finished_at if latest_run else None,
                "latest_records_processed": latest_run.records_processed if latest_run else 0,
                "derived_status": derived_status,
                "status_summary": status_summary,
                "stale_minutes": stale_minutes,
                "blocks_connector_health": config.config_json.get("source_type", SOURCE_TYPES.get(config.source_name, "connector")) != "compute",
                "details_json": details_json or None,
            }
        )
    return rows
