from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_auth
from app.compute.kpis import recompute_daily_kpis, recompute_diagnostics
from app.core.config import get_settings
from app.ingestion.connectors.aws_telemetry import sync_aws_telemetry
from app.ingestion.connectors.clarity import sync_clarity
from app.ingestion.connectors.freshdesk import sync_freshdesk
from app.ingestion.connectors.ga4 import ga4_debug_self_check, sync_ga4
from app.ingestion.connectors.shopify import sync_shopify_orders
from app.ingestion.connectors.triplewhale import sync_triplewhale
from app.models import SourceSyncRun, TelemetryStreamEvent
from app.services.seed import seed_from_prototype_files

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
    else:
        raise HTTPException(status_code=404, detail="Unknown source")

    if _successful_result(result) and not _already_running(db, "decision-engine"):
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
    elif source == "ga4":
        result = sync_ga4(db, days=settings.backfill_days)
    elif source == "clarity":
        result = sync_clarity(db, days=min(3, settings.backfill_days))
    elif source == "aws_telemetry":
        result = sync_aws_telemetry(db, max_records=100000)
    else:
        raise HTTPException(status_code=404, detail="Unknown source")

    if _successful_result(result) and not _already_running(db, "decision-engine"):
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


@router.get('/debug/ga4')
def debug_ga4():
    return ga4_debug_self_check()


@router.get('/debug/telemetry-stream')
def debug_telemetry_stream(db: Session = Depends(db_session)):
    total = db.execute(select(func.count()).select_from(TelemetryStreamEvent)).scalar_one()
    latest = db.execute(
        select(TelemetryStreamEvent)
        .order_by(desc(TelemetryStreamEvent.sample_timestamp), desc(TelemetryStreamEvent.created_at))
        .limit(5)
    ).scalars().all()
    return {
        'total': int(total or 0),
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
