from pathlib import Path
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, distinct, func, select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_auth
from app.compute.kpis import recompute_daily_kpis, recompute_diagnostics
from app.core.config import get_settings
from app.ingestion.connectors.aws_telemetry import sync_aws_telemetry
from app.ingestion.connectors.clarity import sync_clarity
from app.ingestion.connectors.fedex import (
    cross_check_rates as fedex_cross_check_rates,
    health_check as fedex_health_check,
    register_source as fedex_register_source,
)
from app.ingestion.connectors.kpi_inbox import (
    health_check as kpi_inbox_health_check,
    poll_inbox as kpi_inbox_poll,
    register_source as kpi_inbox_register_source,
)
from app.ingestion.connectors.freshdesk import sync_freshdesk
from app.ingestion.connectors.ga4 import ga4_debug_self_check, sync_ga4
from app.ingestion.connectors.shopify import sync_shopify_orders
from app.ingestion.connectors.triplewhale import sync_triplewhale
from app.models import SourceSyncRun, TelemetryHistoryDaily, TelemetrySession, TelemetryStreamEvent
from app.schemas.overview import TelemetryHistoryIngestIn, TelemetryStreamIngestIn
from app.services.cook_rederivation import run_cook_rederivation
from app.services.seed import seed_from_prototype_files
from app.services.source_health import finish_sync_run, start_sync_run, upsert_source_config
from app.services.telemetry_history import upsert_telemetry_history_monthly
from app.streaming.telemetry_stream_writer import write_stream_records

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_auth)])
settings = get_settings()
BASE_DIR = Path(__file__).resolve().parents[4]


def _already_running(db: Session, source: str) -> bool:
    return db.execute(
        select(SourceSyncRun)
        .where(SourceSyncRun.source_name == source, SourceSyncRun.status == "running")
        .order_by(desc(SourceSyncRun.started_at))
        .limit(1)
    ).scalars().first() is not None


def _successful_result(result: dict) -> bool:
    return bool(result.get("ok")) and not bool(result.get("skipped"))


@router.post("/run-sync/{source}")
def run_sync(source: str, db: Session = Depends(db_session)):
    if _already_running(db, source):
        return {"ok": True, "skipped": True, "message": f"{source} sync already running"}

    if source == "shopify":
        result = sync_shopify_orders(db)
    elif source == "triplewhale":
        result = sync_triplewhale(db, backfill_days=1)
    elif source == "freshdesk":
        result = sync_freshdesk(db, days=7)
    elif source == "ga4":
        result = sync_ga4(db, days=7)
    elif source == "clarity":
        result = sync_clarity(db, days=min(3, settings.backfill_days))
    elif source == "aws_telemetry":
        result = sync_aws_telemetry(db)
    elif source == "reddit":
        from app.ingestion.connectors.reddit import sync_reddit
        result = sync_reddit(db)
    elif source == "youtube":
        from app.ingestion.connectors.youtube import sync_youtube
        result = sync_youtube(db)
    elif source == "youtube_lore":
        from app.ingestion.connectors.youtube_lore import sync_youtube_lore
        result = sync_youtube_lore(db)
    elif source == "google_reviews":
        from app.ingestion.connectors.google_reviews import sync_google_reviews
        result = sync_google_reviews(db)
    elif source == "amazon":
        from app.ingestion.connectors.amazon import sync_amazon
        result = sync_amazon(db)
    else:
        raise HTTPException(status_code=404, detail="Unknown source")

    if _successful_result(result) and not _already_running(db, "decision-engine"):
        recompute_daily_kpis(db)
        recompute_diagnostics(db)
    return result


@router.post("/backfill/{source}")
def backfill_source(
    source: str,
    lookback_days: int | None = None,
    max_records: int | None = None,
    max_scan_pages: int | None = None,
    target_devices: int | None = None,
    scan_segments: int | None = None,
    db: Session = Depends(db_session),
):
    if _already_running(db, source):
        return {"ok": True, "skipped": True, "message": f"{source} sync already running"}

    if source == "shopify":
        result = sync_shopify_orders(db, hours=24 * settings.backfill_days)
    elif source == "triplewhale":
        result = sync_triplewhale(db, backfill_days=settings.backfill_days)
    elif source == "freshdesk":
        result = sync_freshdesk(db, days=settings.backfill_days)
    elif source == "ga4":
        result = sync_ga4(db, days=settings.backfill_days)
    elif source == "clarity":
        result = sync_clarity(db, days=min(3, settings.backfill_days))
    elif source == "aws_telemetry":
        requested_lookback_days = max(1, min(int(lookback_days or settings.backfill_days), 3650))
        requested_max_records = max(1000, min(int(max_records or 100000), 2_000_000))
        requested_max_scan_pages = max(1, min(int(max_scan_pages or settings.aws_telemetry_max_scan_pages), 20000))
        requested_target_devices = max(1, min(int(target_devices or settings.aws_telemetry_target_devices_per_sync), 500000))
        requested_scan_segments = max(1, min(int(scan_segments or settings.aws_telemetry_scan_segments), 256))
        result = sync_aws_telemetry(
            db,
            max_records=requested_max_records,
            lookback_hours=requested_lookback_days * 24,
            max_scan_pages=requested_max_scan_pages,
            target_devices_per_sync=requested_target_devices,
            scan_segments=requested_scan_segments,
        )
    elif source == "reddit":
        from app.ingestion.connectors.reddit import sync_reddit
        requested_lookback_hours = max(1, min(int((lookback_days or 7) * 24), 720))
        result = sync_reddit(db, lookback_hours=requested_lookback_hours)
    elif source == "youtube":
        from app.ingestion.connectors.youtube import sync_youtube
        requested_lookback_hours = max(1, min(int((lookback_days or 30) * 24), 720))
        result = sync_youtube(db, lookback_hours=requested_lookback_hours)
    elif source == "google_reviews":
        from app.ingestion.connectors.google_reviews import sync_google_reviews
        result = sync_google_reviews(db)
    elif source == "amazon":
        from app.ingestion.connectors.amazon import sync_amazon
        result = sync_amazon(db)
    else:
        raise HTTPException(status_code=404, detail="Unknown source")

    if _successful_result(result) and not _already_running(db, "decision-engine"):
        recompute_daily_kpis(db)
        recompute_diagnostics(db)
    return result


@router.post("/rederive/cook-quality")
def rederive_cook_quality(
    max_rows: int | None = None,
    db: Session = Depends(db_session),
):
    """Backfill intent/outcome/PID-quality columns on telemetry_sessions
    and rebuild daily aggregates. Idempotent — safe to re-run."""
    return run_cook_rederivation(db, max_rows=max_rows)


@router.post("/seed")
def seed(db: Session = Depends(db_session)):
    seeded = seed_from_prototype_files(db, BASE_DIR)
    if not _already_running(db, "decision-engine"):
        recompute_daily_kpis(db)
        recompute_diagnostics(db)
    return seeded


@router.post("/cache/rebuild")
def rebuild_aggregate_cache(
    key: str | None = None,
    db: Session = Depends(db_session),
):
    """Force-rebuild one or every aggregate-cache builder.

    Normally runs every 15 min via scheduler. Call this when you know
    upstream data has changed and don't want to wait for the next tick
    (e.g. right after an ingest backfill). Returns per-key duration.
    """
    import app.services.cache_builders  # noqa: F401 — registers builders
    from app.services.aggregate_cache import rebuild, rebuild_all, registered_keys
    if key:
        if key not in registered_keys():
            return {"ok": False, "error": f"unknown cache key {key!r}", "available": registered_keys()}
        entry = rebuild(db, key)
        return {"ok": True, "key": key, "duration_ms": entry.duration_ms, "computed_at": entry.computed_at.isoformat()}
    return {"ok": True, "results": rebuild_all(db)}


@router.get("/cache/status")
def aggregate_cache_status(db: Session = Depends(db_session)):
    """Show what's in the aggregate_cache + age + last build duration.
    Useful when a cached endpoint looks wrong."""
    import app.services.cache_builders  # noqa: F401
    from app.services.aggregate_cache import get, registered_keys
    from datetime import datetime as _dt, timezone as _tz
    now = _dt.now(_tz.utc)
    rows = []
    for k in registered_keys():
        entry = get(db, k)
        if entry is None:
            rows.append({"key": k, "present": False})
            continue
        rows.append({
            "key": k,
            "present": True,
            "computed_at": entry.computed_at.isoformat(),
            "age_seconds": (now - entry.computed_at).total_seconds(),
            "duration_ms": entry.duration_ms,
            "source_version": entry.source_version,
        })
    return {"keys": rows}


@router.get('/debug/ga4')
def debug_ga4():
    return ga4_debug_self_check()


@router.get('/debug/fedex')
def debug_fedex(db: Session = Depends(db_session)):
    """Confirm FedEx Web Services creds + endpoint reachability.

    Used to detect when the production project leaves FedEx review and
    flips from sandbox to production. Returns one of:
      * status='healthy'      — production endpoint, token mints OK
      * status='sandbox'      — sandbox endpoint, token mints OK (waiting on prod approval)
      * status='unconfigured' — env vars missing
      * status='error'        — creds set but token mint failed
    Safe to call from anywhere; performs no real data fetching.

    Side effect: calls register_source() to upsert the SourceConfig
    row so System Health surfaces fedex as a known connector even
    before the first real sync runs.
    """
    fedex_register_source(db)
    db.commit()
    return fedex_health_check()


@router.get('/debug/kpi-inbox')
def debug_kpi_inbox(db: Session = Depends(db_session)):
    """Confirm IMAP login + report inbox stats. Idempotent — also
    upserts the source_config row so System Health surfaces this
    connector. No messages read or modified."""
    kpi_inbox_register_source(db)
    db.commit()
    return kpi_inbox_health_check()


@router.post('/run-sync/kpi-inbox')
def run_kpi_inbox_poll(
    max_messages: int = 100,
    mailbox: str = "INBOX",
    db: Session = Depends(db_session),
):
    """Manually trigger the KPI inbox IMAP poll.

    Walks UNSEEN messages, routes through the parser registry,
    persists ledger + parsed records, marks each \\Seen on success.
    The scheduler runs this at 08:00 and 20:00 ET; this route is
    for ad-hoc triggers (post-FBO-export-setup, debugging, etc).
    """
    if _already_running(db, "kpi_inbox"):
        return {"ok": True, "skipped": True, "message": "kpi_inbox sync already running"}
    run = start_sync_run(db, "kpi_inbox", "imap_poll", {"max_messages": max_messages, "mailbox": mailbox})
    db.commit()
    try:
        result = kpi_inbox_poll(db, mailbox=mailbox, max_messages=max_messages)
        finish_sync_run(db, run, status='success', records_processed=int(result.get('records_created_total', 0)))
        db.commit()
        return {"ok": True, **result}
    except Exception as exc:
        finish_sync_run(db, run, status='failure', records_processed=0, error_message=str(exc)[:500])
        db.commit()
        raise


@router.post('/run-sync/fedex/rates')
def run_fedex_rate_cross_check(
    days: int = 7,
    max_shipments: int = 200,
    db: Session = Depends(db_session),
):
    """Manually trigger the FedEx Rates cross-check sync.

    Walks ShipStation FedEx shipments in the last `days` days, asks
    the Rates API for ACCOUNT + LIST quotes per (lane, weight,
    service), and persists the deltas to fedex_rate_quotes.

    Useful for ad-hoc backfills (bump days/max_shipments) and for
    smoke-testing after a credential rotation. The scheduler runs
    this daily at 07:00 ET with the defaults.
    """
    if _already_running(db, "fedex"):
        return {"ok": True, "skipped": True, "message": "fedex sync already running"}
    run = start_sync_run(db, "fedex", "rates_cross_check", {"days": days, "max_shipments": max_shipments})
    db.commit()
    try:
        result = fedex_cross_check_rates(db, days=days, max_shipments=max_shipments)
        finish_sync_run(db, run, status='success', records_processed=int(result.get('quotes_inserted_or_updated', 0)))
        db.commit()
        return {"ok": True, **result}
    except Exception as exc:
        finish_sync_run(db, run, status='failure', records_processed=0, error_message=str(exc)[:500])
        db.commit()
        raise


@router.post('/ingest/telemetry-stream')
def ingest_telemetry_stream(payload: TelemetryStreamIngestIn, db: Session = Depends(db_session)):
    source_name = 'aws_telemetry_stream'
    upsert_source_config(
        db,
        source_name,
        configured=True,
        enabled=True,
        sync_mode='push',
        config_json={
            'source_type': 'connector',
            'input': 'kpi_api_ingest',
            'upstream': 'sg_device_shadows_stream',
        },
    )
    db.commit()

    records = [record.model_dump() for record in payload.records]
    distinct_devices = len({record.get('device_id') for record in records if record.get('device_id')})
    sample_timestamps = [record.get('sample_timestamp') for record in records if record.get('sample_timestamp') is not None]
    run = start_sync_run(db, source_name, 'ingest_telemetry_stream', {
        'records_received': len(records),
        'distinct_devices_received': distinct_devices,
    })
    db.commit()
    try:
        result = write_stream_records(db, records)
        run.metadata_json = {
            **(run.metadata_json or {}),
            'inserted': result.get('inserted', 0),
            'skipped': result.get('skipped', 0),
            'distinct_devices_received': distinct_devices,
            'oldest_sample_timestamp': min(sample_timestamps).isoformat() if sample_timestamps else None,
            'newest_sample_timestamp': max(sample_timestamps).isoformat() if sample_timestamps else None,
        }
        finish_sync_run(db, run, status='success', records_processed=int(result.get('inserted', 0)))
        db.commit()
        return {
            'ok': True,
            'records_received': len(records),
            **result,
        }
    except Exception as exc:
        finish_sync_run(db, run, status='failed', error_message=str(exc))
        db.commit()
        raise


@router.get('/debug/telemetry-stream')
def debug_telemetry_stream(db: Session = Depends(db_session)):
    total = db.execute(select(func.count()).select_from(TelemetryStreamEvent)).scalar_one()
    latest = db.execute(
        select(TelemetryStreamEvent)
        .order_by(desc(TelemetryStreamEvent.sample_timestamp), desc(TelemetryStreamEvent.created_at))
        .limit(5)
    ).scalars().all()
    latest_sample_timestamp = db.execute(
        select(TelemetryStreamEvent.sample_timestamp)
        .where(TelemetryStreamEvent.sample_timestamp.is_not(None))
        .order_by(desc(TelemetryStreamEvent.sample_timestamp))
        .limit(1)
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    rows_last_15m = int(db.execute(
        select(func.count()).select_from(TelemetryStreamEvent).where(TelemetryStreamEvent.created_at >= now - timedelta(minutes=15))
    ).scalar() or 0)
    rows_last_60m = int(db.execute(
        select(func.count()).select_from(TelemetryStreamEvent).where(TelemetryStreamEvent.created_at >= now - timedelta(minutes=60))
    ).scalar() or 0)
    fallback_active = False
    fallback_reason = None
    if latest_sample_timestamp is None or latest_sample_timestamp < now - timedelta(minutes=60):
        fallback_active = True
        fallback_reason = 'No fresh stream rows landed in the last 60 minutes; production may be relying on bounded-scan telemetry again.'
    return {
        'total': int(total or 0),
        'rows_last_15m': rows_last_15m,
        'rows_last_60m': rows_last_60m,
        'latest_sample_timestamp': latest_sample_timestamp,
        'fallback_active': fallback_active,
        'fallback_reason': fallback_reason,
        'latest': [
            {
                'source_event_id': row.source_event_id,
                'device_id': row.device_id,
                'sample_timestamp': row.sample_timestamp,
                'stream_event_name': row.stream_event_name,
                'engaged': row.engaged,
                'firmware_version': row.firmware_version,
                'grill_type': row.grill_type,
                'created_at': row.created_at,
            }
            for row in latest
        ],
    }


@router.post('/ingest/telemetry-history')
def ingest_telemetry_history(payload: TelemetryHistoryIngestIn, db: Session = Depends(db_session)):
    source_name = 'aws_telemetry_history'
    upsert_source_config(
        db,
        source_name,
        configured=True,
        enabled=True,
        sync_mode='manual',
        config_json={
            'source_type': 'connector',
            'input': 'ddb_export_audit',
            'upstream': 'sg_device_shadows_export',
        },
    )
    db.commit()

    run = start_sync_run(db, source_name, 'ingest_telemetry_history', {
        'window_days': payload.window_days,
        'distinct_devices': payload.distinct_devices,
        'distinct_engaged_devices': payload.distinct_engaged_devices,
        'months_received': len(payload.monthly),
        'export_bucket': payload.export_bucket,
        'export_prefix': payload.export_prefix,
        'export_arn': payload.export_arn,
    })
    db.commit()
    try:
        result = upsert_telemetry_history_monthly(
            db,
            monthly_rows=[
                {
                    'month_start': row.month_start,
                    'distinct_devices': row.distinct_devices,
                    'distinct_engaged_devices': row.distinct_engaged_devices,
                }
                for row in payload.monthly
            ],
            window_days=payload.window_days,
            distinct_devices=payload.distinct_devices,
            distinct_engaged_devices=payload.distinct_engaged_devices,
            observed_mac_count=payload.observed_mac_count,
            source=payload.source,
            metadata={
                'export_bucket': payload.export_bucket,
                'export_prefix': payload.export_prefix,
                'export_arn': payload.export_arn,
                'notes': payload.notes,
            },
        )
        finish_sync_run(db, run, status='success', records_processed=int(result.get('months_loaded', 0)))
        db.commit()
        return result
    except Exception as exc:
        finish_sync_run(db, run, status='failed', error_message=str(exc))
        db.commit()
        raise


@router.get('/debug/telemetry-audit')
def debug_telemetry_audit(days: int = 180, db: Session = Depends(db_session)):
    days = max(1, min(days, 3650))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    telemetry_session_rows = int(db.execute(
        select(func.count()).select_from(TelemetrySession).where(TelemetrySession.session_start >= cutoff)
    ).scalar() or 0)
    telemetry_session_devices = int(db.execute(
        select(func.count(distinct(TelemetrySession.device_id))).where(TelemetrySession.session_start >= cutoff, TelemetrySession.device_id.is_not(None))
    ).scalar() or 0)
    telemetry_session_users = int(db.execute(
        select(func.count(distinct(TelemetrySession.user_id))).where(TelemetrySession.session_start >= cutoff, TelemetrySession.user_id.is_not(None))
    ).scalar() or 0)
    telemetry_session_ids = int(db.execute(
        select(func.count(distinct(TelemetrySession.session_id))).where(TelemetrySession.session_start >= cutoff, TelemetrySession.session_id.is_not(None))
    ).scalar() or 0)

    stream_rows = int(db.execute(
        select(func.count()).select_from(TelemetryStreamEvent).where(TelemetryStreamEvent.sample_timestamp >= cutoff)
    ).scalar() or 0)
    stream_devices = int(db.execute(
        select(func.count(distinct(TelemetryStreamEvent.device_id))).where(TelemetryStreamEvent.sample_timestamp >= cutoff)
    ).scalar() or 0)
    engaged_stream_devices = int(db.execute(
        select(func.count(distinct(TelemetryStreamEvent.device_id))).where(TelemetryStreamEvent.sample_timestamp >= cutoff, TelemetryStreamEvent.engaged.is_(True))
    ).scalar() or 0)

    # telemetry_history_daily stats (backfill + materializer status)
    hd_total = int(db.execute(select(func.count()).select_from(TelemetryHistoryDaily)).scalar() or 0)
    hd_min = db.execute(select(func.min(TelemetryHistoryDaily.business_date))).scalar()
    hd_max = db.execute(select(func.max(TelemetryHistoryDaily.business_date))).scalar()
    hd_with_sessions = int(db.execute(
        select(func.count()).select_from(TelemetryHistoryDaily).where(TelemetryHistoryDaily.session_count > 0)
    ).scalar() or 0)
    hd_total_sessions = int(db.execute(
        select(func.sum(TelemetryHistoryDaily.session_count)).select_from(TelemetryHistoryDaily)
    ).scalar() or 0)
    hd_sources = db.execute(
        select(TelemetryHistoryDaily.source, func.count(), func.min(TelemetryHistoryDaily.business_date), func.max(TelemetryHistoryDaily.business_date))
        .group_by(TelemetryHistoryDaily.source)
    ).all()

    return {
        'window_days': days,
        'cutoff': cutoff.isoformat(),
        'telemetry_sessions': {
            'rows': telemetry_session_rows,
            'distinct_devices': telemetry_session_devices,
            'distinct_users': telemetry_session_users,
            'distinct_session_ids': telemetry_session_ids,
        },
        'telemetry_stream_events': {
            'rows': stream_rows,
            'distinct_devices': stream_devices,
            'distinct_engaged_devices': engaged_stream_devices,
        },
        'telemetry_history_daily': {
            'total_days': hd_total,
            'earliest_date': hd_min.isoformat() if hd_min else None,
            'latest_date': hd_max.isoformat() if hd_max else None,
            'days_with_cook_analysis': hd_with_sessions,
            'total_sessions_derived': hd_total_sessions,
            'by_source': [
                {'source': src, 'days': int(cnt), 'earliest': mn.isoformat() if mn else None, 'latest': mx.isoformat() if mx else None}
                for src, cnt, mn, mx in hd_sources
            ],
        },
    }
