"""Partner product-catalog scraper.

Today just Jealous Devil; shape is generic so Royal Oak / Kingsford
/ other charcoal partners slot in under ``PARTNERS`` without schema
changes.

Mechanism: Shopify publishes a standard ``/products.json`` endpoint
on every storefront. We fetch the public JSON, filter to
charcoal-relevant products (by handle/title keywords), parse bag
size + fuel type out of the title, and upsert into
``partner_products``.

Runs daily via ``run_partner_catalog_refresh_job``. Manual refresh
also available via ``POST /api/charcoal/partners/refresh``.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PartnerProduct

logger = logging.getLogger(__name__)


# Each partner declares: the base storefront URL (for source_url + the
# products.json fetch) and a filter that drops non-charcoal items
# (merch, patches, etc.) so the catalog stays clean.
PARTNERS: dict[str, dict[str, Any]] = {
    "jealous_devil": {
        "storefront": "https://jealousdevil.com",
        "filter_keywords": ("lump", "briquet", "charcoal"),
        # Items to exclude even if they contain the keywords — e.g.
        # merchandise that references charcoal in the title.
        "exclude_keywords": ("patch", "hat", "shirt", "sticker", "pin", "swag"),
    },
}

_REQUEST_TIMEOUT_SECONDS = 20
_USER_AGENT = "SpiderGrills-KPI/1.0 (partner-catalog-fetcher; ops@spidergrills.com)"


def _infer_fuel_type(title: str, handle: str) -> Optional[str]:
    low = f"{title} {handle}".lower()
    # Briquette typo is common ("briquets" without the second 't'); catch both.
    if "briquet" in low:
        return "briquette"
    if "lump" in low:
        return "lump"
    return None


def _infer_bag_size_lb(title: str, handle: str) -> Optional[int]:
    """Pull a weight out of the title. Common patterns:
      '35 Pounds', '20 lb', '20-lb', '20lb'. Kilos converted to lb.
    """
    text = f"{title} {handle}"
    # First match wins; most titles have exactly one weight.
    m = re.search(r"(\d{1,3})\s*(?:lb|lbs|pound|pounds|-?lb)\b", text, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    # Kilograms → lb
    m = re.search(r"(\d{1,3})\s*(?:kg|kilogram|kilos?)\b", text, re.IGNORECASE)
    if m:
        try:
            return int(round(int(m.group(1)) * 2.20462))
        except ValueError:
            return None
    return None


def _matches_filter(handle: str, title: str, cfg: dict[str, Any]) -> bool:
    low = f"{handle} {title}".lower()
    if not any(k in low for k in cfg["filter_keywords"]):
        return False
    if any(k in low for k in cfg["exclude_keywords"]):
        return False
    return True


def fetch_partner_catalog(partner_key: str) -> dict[str, Any]:
    """Fetch + upsert one partner's catalog. Returns stats dict."""
    cfg = PARTNERS.get(partner_key)
    if cfg is None:
        return {"ok": False, "error": f"unknown partner {partner_key!r}"}

    url = f"{cfg['storefront'].rstrip('/')}/products.json?limit=250"
    try:
        r = requests.get(url, timeout=_REQUEST_TIMEOUT_SECONDS, headers={"User-Agent": _USER_AGENT})
        r.raise_for_status()
        payload = r.json()
    except Exception as exc:
        logger.exception("partner catalog fetch failed for %s", partner_key)
        return {"ok": False, "partner": partner_key, "error": f"fetch_failed: {exc}"}

    products = payload.get("products") or []
    return {"ok": True, "partner": partner_key, "products": products, "storefront": cfg["storefront"]}


def upsert_partner_catalog(db: Session, partner_key: str) -> dict[str, Any]:
    """Fetch partner catalog and write the filtered subset to the DB.

    Products in DB that aren't in the latest fetch get marked
    ``available=False`` (partner removed or renamed) rather than
    deleted — we want historical price continuity if a SKU comes back.
    """
    fetch = fetch_partner_catalog(partner_key)
    if not fetch.get("ok"):
        return fetch
    cfg = PARTNERS[partner_key]
    storefront = fetch["storefront"]
    fetched_handles: set[str] = set()
    stats = {
        "partner": partner_key,
        "products_fetched": 0,
        "products_matched": 0,
        "inserted": 0,
        "updated": 0,
        "marked_unavailable": 0,
    }

    now = datetime.now(timezone.utc)
    for p in fetch["products"]:
        stats["products_fetched"] += 1
        handle = (p.get("handle") or "").strip()
        title = (p.get("title") or "").strip()
        if not handle or not title:
            continue
        if not _matches_filter(handle, title, cfg):
            continue
        stats["products_matched"] += 1
        fetched_handles.add(handle)

        variants = p.get("variants") or []
        if not variants:
            continue
        # First variant is the default. Shopify price strings like "49.99".
        variant = variants[0]
        try:
            price = float(variant.get("price") or 0.0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        available = bool(variant.get("available"))
        fuel = _infer_fuel_type(title, handle)
        bag_size = _infer_bag_size_lb(title, handle)
        source_url = f"{storefront}/products/{handle}"

        existing = db.execute(
            select(PartnerProduct).where(
                PartnerProduct.partner == partner_key,
                PartnerProduct.handle == handle,
            )
        ).scalars().first()

        if existing is None:
            db.add(PartnerProduct(
                partner=partner_key,
                handle=handle,
                title=title,
                fuel_type=fuel,
                bag_size_lb=bag_size,
                retail_price_usd=price,
                currency="USD",
                source_url=source_url,
                available=available,
                last_fetched_at=now,
                raw_payload=p,
            ))
            stats["inserted"] += 1
        else:
            existing.title = title
            existing.fuel_type = fuel
            existing.bag_size_lb = bag_size
            existing.retail_price_usd = price
            existing.source_url = source_url
            existing.available = available
            existing.last_fetched_at = now
            existing.raw_payload = p
            stats["updated"] += 1

    # Any product we've seen before but didn't see this pass → mark unavailable.
    known = db.execute(
        select(PartnerProduct).where(PartnerProduct.partner == partner_key)
    ).scalars().all()
    for row in known:
        if row.handle not in fetched_handles and row.available:
            row.available = False
            stats["marked_unavailable"] += 1

    db.commit()
    stats["computed_at"] = now.isoformat()
    stats["ok"] = True
    return stats


def refresh_all_partners(db: Session) -> dict[str, Any]:
    """Refresh every registered partner. Used by the scheduler and by
    the ``POST /api/charcoal/partners/refresh`` endpoint."""
    results = []
    for key in PARTNERS:
        results.append(upsert_partner_catalog(db, key))
    return {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "partners_refreshed": len(results),
        "results": results,
    }
