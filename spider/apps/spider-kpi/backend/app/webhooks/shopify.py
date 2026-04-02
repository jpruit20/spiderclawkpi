import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.ingestion.connectors.shopify import store_webhook_event, verify_shopify_hmac

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
    return {"ok": True, "event_id": event.id}
