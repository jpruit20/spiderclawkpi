from pathlib import Path
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from app.compute.app_side import materialize_app_side
from app.compute.kpis import recompute_daily_kpis, recompute_diagnostics
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.ingestion.connectors.aws_telemetry import sync_aws_telemetry
from app.ingestion.connectors.clarity import sync_clarity
from app.ingestion.connectors.clickup import sync_clickup
from app.ingestion.connectors.freshdesk import sync_freshdesk
from app.ingestion.connectors.ga4 import sync_ga4
from app.ingestion.connectors.shopify import sync_shopify_orders
from app.ingestion.connectors.slack import sync_slack
from app.ingestion.connectors.triplewhale import sync_triplewhale
from app.models import SourceConfig, SourceSyncRun
from app.services.seed import seed_from_prototype_files
from sqlalchemy import desc, select


settings = get_settings()
BASE_DIR = Path(__file__).resolve().parents[2]


def _already_running(db, source_name: str) -> bool:
    """Check if a connector is already running. Auto-expires stale runs (>30 min)."""
    run = db.execute(
        select(SourceSyncRun)
        .where(SourceSyncRun.source_name == source_name, SourceSyncRun.status == "running")
        .order_by(desc(SourceSyncRun.started_at))
        .limit(1)
    ).scalars().first()
    if run is None:
        return False
    started_at = run.started_at or run.created_at
    if started_at and started_at < datetime.now(timezone.utc) - timedelta(minutes=30):
        run.status = "failed"
        run.finished_at = datetime.now(timezone.utc)
        run.error_message = "Stale running sync auto-expired by scheduler (>30 min)."
        run.metadata_json = {**(run.metadata_json or {}), "auto_expired": True, "expired_at": datetime.now(timezone.utc).isoformat()}
        db.add(run)
        db.commit()
        return False  # allow new run to start
    return True


def _successful_result(result: dict | None) -> bool:
    if not result:
        return False
    return bool(result.get("ok")) and not bool(result.get("skipped"))


def run_seed() -> None:
    db = SessionLocal()
    try:
        existing_live_configs = db.execute(
            select(SourceConfig).where(
                SourceConfig.source_name.in_(["shopify", "triplewhale", "ga4", "clarity", "freshdesk", "aws_telemetry"])
            )
        ).scalars().all()
        if any(
            cfg and cfg.configured and (cfg.sync_mode or "") != "seeded-prototype"
            for cfg in existing_live_configs
        ):
            return
        seeded = seed_from_prototype_files(db, BASE_DIR)
        if any(seeded.values()) and not _already_running(db, "decision-engine"):
            recompute_daily_kpis(db)
            recompute_diagnostics(db)
    finally:
        db.close()


def run_syncs() -> None:
    db = SessionLocal()
    try:
        any_success = False
        if not _already_running(db, "shopify"):
            any_success = _successful_result(sync_shopify_orders(db)) or any_success
        if not _already_running(db, "triplewhale"):
            any_success = _successful_result(sync_triplewhale(db, backfill_days=1)) or any_success
        freshdesk_success = False
        if not _already_running(db, "freshdesk"):
            freshdesk_success = _successful_result(sync_freshdesk(db, days=7))
            any_success = freshdesk_success or any_success
        if freshdesk_success:
            try:
                materialize_app_side(db)
            except Exception:
                # Materializer failure should not abort the scheduler sweep.
                import logging
                logging.getLogger(__name__).exception("app_side materialize failed")
                db.rollback()
        if not _already_running(db, "ga4"):
            any_success = _successful_result(sync_ga4(db, days=7)) or any_success
        if not _already_running(db, "aws_telemetry"):
            any_success = _successful_result(sync_aws_telemetry(db)) or any_success
        latest_clarity_run = db.execute(
            select(SourceSyncRun)
            .where(SourceSyncRun.source_name == "clarity")
            .order_by(desc(SourceSyncRun.started_at))
            .limit(1)
        ).scalar_one_or_none()
        clarity_due = (
            latest_clarity_run is None
            or latest_clarity_run.started_at is None
            or latest_clarity_run.started_at <= datetime.now(timezone.utc) - timedelta(minutes=settings.clarity_sync_interval_minutes)
        )
        if clarity_due and not _already_running(db, "clarity"):
            any_success = _successful_result(sync_clarity(db, days=1)) or any_success
        latest_reddit_run = db.execute(
            select(SourceSyncRun)
            .where(SourceSyncRun.source_name == "reddit")
            .order_by(desc(SourceSyncRun.started_at))
            .limit(1)
        ).scalar_one_or_none()
        reddit_due = (
            latest_reddit_run is None
            or latest_reddit_run.started_at is None
            or latest_reddit_run.started_at <= datetime.now(timezone.utc) - timedelta(minutes=settings.reddit_sync_interval_minutes)
        )
        if reddit_due and not _already_running(db, "reddit"):
            from app.ingestion.connectors.reddit import sync_reddit
            any_success = _successful_result(sync_reddit(db)) or any_success
        latest_amazon_run = db.execute(
            select(SourceSyncRun)
            .where(SourceSyncRun.source_name == "amazon")
            .order_by(desc(SourceSyncRun.started_at))
            .limit(1)
        ).scalar_one_or_none()
        amazon_due = (
            latest_amazon_run is None
            or latest_amazon_run.started_at is None
            or latest_amazon_run.started_at <= datetime.now(timezone.utc) - timedelta(minutes=settings.amazon_sync_interval_minutes)
        )
        if amazon_due and not _already_running(db, "amazon"):
            from app.ingestion.connectors.amazon import sync_amazon
            any_success = _successful_result(sync_amazon(db)) or any_success
        latest_clickup_run = db.execute(
            select(SourceSyncRun)
            .where(SourceSyncRun.source_name == "clickup")
            .order_by(desc(SourceSyncRun.started_at))
            .limit(1)
        ).scalar_one_or_none()
        clickup_due = (
            latest_clickup_run is None
            or latest_clickup_run.started_at is None
            or latest_clickup_run.started_at <= datetime.now(timezone.utc) - timedelta(minutes=settings.clickup_sync_interval_minutes)
        )
        if clickup_due and not _already_running(db, "clickup"):
            any_success = _successful_result(sync_clickup(db)) or any_success
        latest_slack_run = db.execute(
            select(SourceSyncRun)
            .where(SourceSyncRun.source_name == "slack")
            .order_by(desc(SourceSyncRun.started_at))
            .limit(1)
        ).scalar_one_or_none()
        slack_due = (
            latest_slack_run is None
            or latest_slack_run.started_at is None
            or latest_slack_run.started_at <= datetime.now(timezone.utc) - timedelta(minutes=settings.slack_discovery_interval_minutes)
        )
        if slack_due and not _already_running(db, "slack"):
            any_success = _successful_result(sync_slack(db)) or any_success
        latest_youtube_run = db.execute(
            select(SourceSyncRun)
            .where(SourceSyncRun.source_name == "youtube")
            .order_by(desc(SourceSyncRun.started_at))
            .limit(1)
        ).scalar_one_or_none()
        youtube_due = (
            latest_youtube_run is None
            or latest_youtube_run.started_at is None
            or latest_youtube_run.started_at <= datetime.now(timezone.utc) - timedelta(minutes=360)
        )
        if youtube_due and not _already_running(db, "youtube"):
            from app.ingestion.connectors.youtube import sync_youtube
            any_success = _successful_result(sync_youtube(db)) or any_success
        if any_success and not _already_running(db, "decision-engine"):
            recompute_daily_kpis(db)
            recompute_diagnostics(db)
    finally:
        db.close()


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(run_seed, "date", id="seed-on-start", max_instances=1, coalesce=True)
    scheduler.add_job(run_syncs, "interval", minutes=settings.sync_interval_minutes, id="sync-all", replace_existing=True, max_instances=1, coalesce=True)
    return scheduler
