"""ShipStation v1 connector — Spider-only shipments.

Pulls shipments from ``ssapi.shipstation.com/shipments`` filtered by
the configured Spider store allowlist (Amazon + Shopify + Manual).
The mirror powers the shipping-cost-into-COGS rollup so gross-profit
math reflects what we actually paid carriers.

Two modes (auto-selected):
1. **Historical backfill** — when ``shipstation_shipments`` is empty,
   walk backward in 30-day windows from today out to
   ``shipstation_initial_backfill_days`` (default 4y). Each window
   filters by ``createDateStart``/``createDateEnd`` so we don't have
   to hold the full history in memory.
2. **Delta sync** — on subsequent runs, fetch shipments
   ``createDateStart = max(create_date) - 1 day`` so any late-modified
   rows get picked up.

Rate limits: ShipStation v1 caps at **40 req/min** per API key. The
client respects the ``X-Rate-Limit-Remaining`` header and sleeps when
it goes low. Each ``/shipments`` call is paginated 500 rows per page.

Filtering:
- Server-side: ``storeId=N`` per allow-listed store, one pass per store
- Client-side: every persisted row's ``ss_store_id`` is checked against
  the allowlist before INSERT, so a misconfig can't leak rows from
  the other companies' stores

Idempotency: ``ss_shipment_id`` is unique. ON CONFLICT DO UPDATE on
mutable fields (cost, voided, tracking) so re-syncs heal stale rows.
"""
from __future__ import annotations

import base64
import logging
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterator, Optional

import requests
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ShipstationShipment, ShipstationStore


logger = logging.getLogger(__name__)

BASE_URL = "https://ssapi.shipstation.com"
PAGE_SIZE = 500
RATE_LIMIT_LOW_WATER = 5  # sleep when fewer remaining requests than this
WINDOW_DAYS = 30  # historical backfill chunk


def _client_headers() -> dict[str, str]:
    settings = get_settings()
    if not (settings.shipstation_api_key and settings.shipstation_api_secret):
        raise RuntimeError("SHIPSTATION_API_KEY / SHIPSTATION_API_SECRET not configured")
    creds = f"{settings.shipstation_api_key}:{settings.shipstation_api_secret}".encode()
    basic = base64.b64encode(creds).decode()
    return {
        "Authorization": f"Basic {basic}",
        "Accept": "application/json",
    }


def _get(path: str, params: Optional[dict[str, Any]] = None, *, timeout: int = 30) -> dict[str, Any]:
    """Single GET respecting rate-limit headers. Sleeps when remaining
    drops below RATE_LIMIT_LOW_WATER. Retries once on 429."""
    url = f"{BASE_URL}{path}"
    for attempt in range(2):
        r = requests.get(url, params=params, headers=_client_headers(), timeout=timeout)
        if r.status_code == 429:
            wait = int(r.headers.get("X-Rate-Limit-Reset", "60"))
            logger.warning("shipstation 429, sleeping %ss before retry", wait)
            time.sleep(wait + 1)
            continue
        r.raise_for_status()
        # Polite back-off on rate-limit window
        try:
            remaining = int(r.headers.get("X-Rate-Limit-Remaining", "40"))
            reset = int(r.headers.get("X-Rate-Limit-Reset", "0"))
            if remaining <= RATE_LIMIT_LOW_WATER and reset > 0:
                logger.info("shipstation rate-limit low (%d remaining), sleeping %ss", remaining, reset)
                time.sleep(reset + 1)
        except Exception:
            pass
        return r.json()
    raise RuntimeError("shipstation: rate-limit retry exhausted")


# ── Stores ──────────────────────────────────────────────────────────


def sync_stores(db: Session) -> dict[str, int]:
    """Mirror /stores, marking Spider-only ones with included_in_spider=True."""
    settings = get_settings()
    allowlist = set(settings.shipstation_spider_store_ids or [])
    body = _get("/stores")
    if not isinstance(body, list):
        raise RuntimeError(f"unexpected /stores shape: {type(body).__name__}")

    counts = {"seen": 0, "upserted": 0, "spider": 0}
    for s in body:
        counts["seen"] += 1
        ss_id = int(s.get("storeId") or 0)
        if not ss_id:
            continue
        existing = db.execute(
            select(ShipstationStore).where(ShipstationStore.ss_store_id == ss_id)
        ).scalar_one_or_none()
        if existing is None:
            existing = ShipstationStore(ss_store_id=ss_id)
            db.add(existing)
        existing.store_name = s.get("storeName") or ""
        existing.marketplace = s.get("marketplaceName")
        existing.active = bool(s.get("active", True))
        existing.included_in_spider = ss_id in allowlist
        if existing.included_in_spider:
            counts["spider"] += 1
        counts["upserted"] += 1
    db.commit()
    return counts


# ── Shipments ───────────────────────────────────────────────────────


def _parse_dt(s: Any) -> Optional[datetime]:
    if not s:
        return None
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    try:
        # ShipStation returns "2026-04-26T08:13:00.0000000" (no TZ)
        # — assume UTC.
        s = str(s).replace("Z", "")
        if "." in s:
            base, frac = s.split(".", 1)
            s = base + "." + frac[:6]  # truncate to microseconds
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc) if "+" not in s else datetime.fromisoformat(s)
    except Exception:
        return None


def _parse_date(s: Any) -> Optional[date]:
    dt = _parse_dt(s)
    return dt.date() if dt else None


def _to_decimal(v: Any) -> Optional[Decimal]:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def _persist_shipment(db: Session, payload: dict[str, Any], allowlist: set[int]) -> bool:
    """Upsert one shipment. Returns True if persisted, False if filtered out."""
    ss_shipment_id = int(payload.get("shipmentId") or 0)
    if not ss_shipment_id:
        return False
    store_id = int(payload.get("storeId") or 0)
    if store_id not in allowlist:
        # Defense-in-depth: server-side filter SHOULD have caught it, but
        # we re-check on the way in.
        return False

    existing = db.execute(
        select(ShipstationShipment).where(ShipstationShipment.ss_shipment_id == ss_shipment_id)
    ).scalar_one_or_none()
    if existing is None:
        existing = ShipstationShipment(ss_shipment_id=ss_shipment_id, ss_store_id=store_id)
        db.add(existing)

    ship_to = payload.get("shipTo") or {}
    dims = payload.get("dimensions") or {}

    existing.ss_order_id = int(payload.get("orderId")) if payload.get("orderId") else None
    existing.ss_order_number = (payload.get("orderNumber") or "")[:128] or None
    existing.ss_store_id = store_id
    existing.customer_email = (payload.get("customerEmail") or "")[:255] or None
    existing.shipment_cost = _to_decimal(payload.get("shipmentCost")) or Decimal("0")
    existing.insurance_cost = _to_decimal(payload.get("insuranceCost")) or Decimal("0")
    existing.carrier_code = (payload.get("carrierCode") or "")[:64] or None
    existing.service_code = (payload.get("serviceCode") or "")[:64] or None
    existing.package_code = (payload.get("packageCode") or "")[:64] or None
    existing.tracking_number = (payload.get("trackingNumber") or "")[:255] or None
    existing.ship_date = _parse_date(payload.get("shipDate"))
    existing.create_date = _parse_dt(payload.get("createDate"))
    existing.void_date = _parse_dt(payload.get("voidDate"))
    existing.voided = bool(payload.get("voided", False))
    existing.weight_oz = _to_decimal((payload.get("weight") or {}).get("value"))
    existing.dimensions_json = dims if isinstance(dims, dict) else {}
    existing.warehouse_id = int(payload.get("warehouseId")) if payload.get("warehouseId") else None
    existing.ship_to_state = (ship_to.get("state") or "")[:64] or None
    existing.ship_to_country = (ship_to.get("country") or "")[:8] or None
    existing.raw_payload = payload
    return True


def _shipments_iter(
    *,
    store_id: int,
    create_date_start: datetime,
    create_date_end: datetime,
) -> Iterator[dict[str, Any]]:
    """Paginate /shipments for one store + window. ShipStation returns
    ``shipments``, ``total``, ``page``, ``pages``."""
    page = 1
    while True:
        body = _get("/shipments", params={
            "storeId": store_id,
            "createDateStart": create_date_start.strftime("%Y-%m-%d %H:%M:%S"),
            "createDateEnd": create_date_end.strftime("%Y-%m-%d %H:%M:%S"),
            "pageSize": PAGE_SIZE,
            "page": page,
            "includeShipmentItems": "false",  # we cross-ref via order_number against Shopify line_items
        })
        rows = body.get("shipments") or []
        for r in rows:
            yield r
        pages = int(body.get("pages") or 1)
        if page >= pages:
            return
        page += 1


def sync_shipments(db: Session) -> dict[str, int]:
    """Pull shipments for every Spider store. Auto-selects mode:
    backfill if table is empty, delta otherwise."""
    settings = get_settings()
    allowlist = set(settings.shipstation_spider_store_ids or [])
    if not allowlist:
        return {"reason": "no Spider stores configured", "ingested": 0}

    # Determine starting cutoff per store
    latest_create = db.execute(
        select(text("MAX(create_date)")).select_from(text("shipstation_shipments"))
    ).scalar()
    is_backfill = latest_create is None
    now = datetime.now(timezone.utc)
    if is_backfill:
        global_start = now - timedelta(days=settings.shipstation_initial_backfill_days)
        logger.warning("shipstation: backfill mode, walking from %s back to %s in %d-day windows",
                       now.isoformat(), global_start.isoformat(), WINDOW_DAYS)
    else:
        # 1-day overlap to catch updates
        global_start = (latest_create - timedelta(days=1)) if latest_create.tzinfo else latest_create.replace(tzinfo=timezone.utc) - timedelta(days=1)
        logger.info("shipstation: delta mode from %s", global_start.isoformat())

    counts = {"seen": 0, "upserted": 0, "filtered": 0, "errors": 0}

    for store_id in sorted(allowlist):
        logger.info("shipstation: store %d, walking windows", store_id)
        # Walk forward in 30-day windows from global_start to now
        window_start = global_start
        while window_start < now:
            window_end = min(window_start + timedelta(days=WINDOW_DAYS), now)
            try:
                for payload in _shipments_iter(
                    store_id=store_id,
                    create_date_start=window_start,
                    create_date_end=window_end,
                ):
                    counts["seen"] += 1
                    try:
                        if _persist_shipment(db, payload, allowlist):
                            counts["upserted"] += 1
                        else:
                            counts["filtered"] += 1
                    except Exception:
                        logger.exception("shipstation: per-row persist failed; skipping")
                        counts["errors"] += 1
                        db.rollback()
                # Commit per-window so a mid-walk failure doesn't lose everything.
                db.commit()
            except Exception:
                logger.exception("shipstation: window %s -> %s failed", window_start, window_end)
                db.rollback()
                counts["errors"] += 1
            window_start = window_end

    return counts


def sync_shipstation(db: Session) -> dict[str, int]:
    """Top-level entry — refresh stores, then shipments."""
    out: dict[str, Any] = {"stores": sync_stores(db), "shipments": sync_shipments(db)}
    return out
