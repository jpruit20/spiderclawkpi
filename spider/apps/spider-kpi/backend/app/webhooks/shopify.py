import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.compute.kpis import recompute_daily_kpis, recompute_diagnostics
from app.ingestion.connectors.shopify import rebuild_shopify_daily_from_events, store_webhook_event, verify_shopify_hmac

router = APIRouter(prefix="/webhooks/shopify", tags=["shopify-webhooks"])


@router.post("/{topic}")
async def handle_shopify_webhook(
    topic: str,
    request: Request,
    db: Session = Depends(db_session),
    x_shopify_hmac_sha256: str | None = Header(default=None),
):
    raw_body = await request.body()
    if not verify_shopify_hmac(raw_body, x_shopify_hmac_sha256):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = json.loads(raw_body.decode("utf-8"))
    event = store_webhook_event(db, topic, payload)
    touched_dates = {event.business_date} if event.business_date else set()
    rebuild_shopify_daily_from_events(db, touched_dates)
    recompute_daily_kpis(db)
    recompute_diagnostics(db)
    return {"ok": True, "event_id": event.id, "business_dates_rebuilt": len(touched_dates)}
