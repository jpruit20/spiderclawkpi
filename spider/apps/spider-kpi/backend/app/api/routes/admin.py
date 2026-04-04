from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_auth
from app.compute.kpis import recompute_daily_kpis, recompute_diagnostics
from app.core.config import get_settings
from app.ingestion.connectors.freshdesk import sync_freshdesk
from app.ingestion.connectors.shopify import sync_shopify_orders
from app.ingestion.connectors.triplewhale import sync_triplewhale
from app.models import SourceSyncRun
from app.services.seed import seed_from_prototype_files

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_auth)])
settings = get_settings()
BASE_DIR = Path("/home/jpruit20/.openclaw/workspace/spider/apps/spider-kpi")


def _already_running(db: Session, source: str) -> bool:
    return db.execute(
        select(SourceSyncRun)
        .where(SourceSyncRun.source_name == source, SourceSyncRun.status == "running")
        .order_by(desc(SourceSyncRun.started_at))
        .limit(1)
    ).scalars().first() is not None


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
    else:
        raise HTTPException(status_code=404, detail="Unknown source")

    if not _already_running(db, "decision-engine"):
        recompute_daily_kpis(db)
        recompute_diagnostics(db)
    return result


@router.post("/backfill/{source}")
def backfill_source(source: str, db: Session = Depends(db_session)):
    if _already_running(db, source):
        return {"ok": True, "skipped": True, "message": f"{source} sync already running"}

    if source == "shopify":
        result = sync_shopify_orders(db, hours=24 * settings.backfill_days)
    elif source == "triplewhale":
        result = sync_triplewhale(db, backfill_days=settings.backfill_days)
    elif source == "freshdesk":
        result = sync_freshdesk(db, days=settings.backfill_days)
    else:
        raise HTTPException(status_code=404, detail="Unknown source")

    if not _already_running(db, "decision-engine"):
        recompute_daily_kpis(db)
        recompute_diagnostics(db)
    return result


@router.post("/seed")
def seed(db: Session = Depends(db_session)):
    seeded = seed_from_prototype_files(db, BASE_DIR)
    if not _already_running(db, "decision-engine"):
        recompute_daily_kpis(db)
        recompute_diagnostics(db)
    return seeded
