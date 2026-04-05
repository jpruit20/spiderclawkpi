from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler

from app.compute.kpis import recompute_daily_kpis, recompute_diagnostics
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.ingestion.connectors.clarity import sync_clarity
from app.ingestion.connectors.freshdesk import sync_freshdesk
from app.ingestion.connectors.ga4 import sync_ga4
from app.ingestion.connectors.shopify import sync_shopify_orders
from app.ingestion.connectors.triplewhale import sync_triplewhale
from app.models import SourceConfig, SourceSyncRun
from app.services.seed import seed_from_prototype_files
from sqlalchemy import desc, select


settings = get_settings()
BASE_DIR = Path(__file__).resolve().parents[2]


def _already_running(db, source_name: str) -> bool:
    return db.execute(
        select(SourceSyncRun)
        .where(SourceSyncRun.source_name == source_name, SourceSyncRun.status == "running")
        .order_by(desc(SourceSyncRun.started_at))
        .limit(1)
    ).scalars().first() is not None


def _successful_result(result: dict | None) -> bool:
    if not result:
        return False
    return bool(result.get("ok")) and not bool(result.get("skipped"))


def run_seed() -> None:
    db = SessionLocal()
    try:
        existing_live_configs = db.execute(
            select(SourceConfig).where(
                SourceConfig.source_name.in_(["shopify", "triplewhale", "ga4", "clarity", "freshdesk"])
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
        if not _already_running(db, "freshdesk"):
            any_success = _successful_result(sync_freshdesk(db, days=7)) or any_success
        if not _already_running(db, "ga4"):
            any_success = _successful_result(sync_ga4(db, days=7)) or any_success
        if not _already_running(db, "clarity"):
            any_success = _successful_result(sync_clarity(db, days=3)) or any_success
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
