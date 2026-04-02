from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler

from app.compute.kpis import recompute_daily_kpis, recompute_diagnostics
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.ingestion.connectors.freshdesk import sync_freshdesk
from app.ingestion.connectors.shopify import sync_shopify_orders
from app.ingestion.connectors.triplewhale import sync_triplewhale
from app.models import SourceSyncRun
from app.services.seed import seed_from_prototype_files
from sqlalchemy import desc, select


settings = get_settings()
BASE_DIR = Path("/home/jpruit20/.openclaw/workspace/spider-kpi")


def _already_running(db, source_name: str) -> bool:
    return db.execute(
        select(SourceSyncRun)
        .where(SourceSyncRun.source_name == source_name, SourceSyncRun.status == "running")
        .order_by(desc(SourceSyncRun.started_at))
        .limit(1)
    ).scalars().first() is not None


def run_seed() -> None:
    db = SessionLocal()
    try:
        seed_from_prototype_files(db, BASE_DIR)
        if not _already_running(db, "decision-engine"):
            recompute_daily_kpis(db)
            recompute_diagnostics(db)
    finally:
        db.close()


def run_syncs() -> None:
    db = SessionLocal()
    try:
        if not _already_running(db, "shopify"):
            sync_shopify_orders(db)
        if not _already_running(db, "triplewhale"):
            sync_triplewhale(db, backfill_days=1)
        if not _already_running(db, "freshdesk"):
            sync_freshdesk(db, days=7)
        if not _already_running(db, "decision-engine"):
            recompute_daily_kpis(db)
            recompute_diagnostics(db)
    finally:
        db.close()


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(run_seed, "date", id="seed-on-start", max_instances=1, coalesce=True)
    scheduler.add_job(run_syncs, "interval", minutes=settings.sync_interval_minutes, id="sync-all", replace_existing=True, max_instances=1, coalesce=True)
    return scheduler
