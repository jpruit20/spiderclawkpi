"""Partner product-catalog scraper.

Today just Jealous Devil; shape is generic so Royal Oak / Kingsford
/ other charcoal partners slot in under ``PARTNERS`` without schema
changes.

Mechanism: Shopify publishes a standard ``/products.json`` endpoint
on every storefront. We fetch the public JSON, filter to charcoal
SKUs that fit the 2026 JIT beta scope, parse bag size + category +
fuel type, and upsert into ``partner_products``.

2026-04-22 scope (Joseph): only ingest SKUs whose title contains
"lump" or "briquette". Specialty lines (Hex Supernatural, binchotan)
and non-charcoal consumables (firestarters, firelogs, pellets) are
deliberately excluded from the modeling surface — we don't want the
cohort calculator offering SKUs we can't predict burn-rate for.

Shipping is 100% on Jealous Devil's side; we never touch the
charcoal physically, so nothing in this module or downstream
modeling should add shipping into the Spider Grills margin math.

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
# products.json fetch) and a filter that drops non-charcoal items so
# the catalog stays clean.
#
# ``include_title_keywords`` — the title must contain at least one of
# these (case-insensitive). Using "briquet" catches both "briquette"
# and the "briquets" typo some JD SKUs carry.
#
# ``exclude_title_keywords`` — even if a title matches the include
# list, any of these kills it. "supernatural" and "binchotan" block
# JD's specialty lines per Joseph's 2026-04-22 scoping call.
#
# ``exclude_tags`` — Shopify products.json ships tags as either a
# string or a list depending on the store. Anything tagged "merch"
# on JD's store is apparel / swag — drop it regardless of title.
PARTNERS: dict[str, dict[str, Any]] = {
    "jealous_devil": {
        "storefront": "https://jealousdevil.com",
        "include_title_keywords": ("lump", "briquet"),
        "exclude_title_keywords": (
            "supernatural",   # Hex Supernatural = premium binchotan-style
            "binchotan",
            "patch", "hat", "shirt", "sticker", "pin", "swag",
        ),
        "exclude_tags": ("merch",),
    },
}

_REQUEST_TIMEOUT_SECONDS = 20
_USER_AGENT = "SpiderGrills-KPI/1.0 (partner-catalog-fetcher; ops@spidergrills.com)"
_GRAMS_PER_LB = 453.59237


def _infer_fuel_type(title: str, handle: str) -> Optional[str]:
    low = f"{title} {handle}".lower()
    # Briquette typo is common ("briquets" without the second 't'); catch both.
    if "briquet" in low:
        return "briquette"
    if "lump" in low:
        return "lump"
    return None


def _infer_category(title: str, handle: str) -> str:
    """Map a product to a modeling bucket. Stays aligned with the
    include filter — anything that makes it past the scraper will land
    in 'lump_charcoal' or 'briquette'. 'other' is only returned if we
    ever relax ``include_title_keywords`` and start letting e.g.
    firestarters through."""
    fuel = _infer_fuel_type(title, handle)
    if fuel == "lump":
        return "lump_charcoal"
    if fuel == "briquette":
        return "briquette"
    return "other"


_TITLE_LB_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:lb|lbs|pound|pounds|-?lb)\b", re.IGNORECASE)
_TITLE_KG_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:kg|kilogram|kilos?)\b", re.IGNORECASE)


def _infer_bag_size_lb(title: str, handle: str, variant: dict[str, Any]) -> Optional[int]:
    """Pull a weight out of the title first; fall back to
    ``variants[0].grams`` if the title doesn't advertise a weight. A
    few JD SKUs just say "XL Bag" with no number in the title — the
    Shopify variant payload is the safety net.

    Common title patterns: '35 Pounds', '20 lb', '20-lb', '20lb', '20.5 lb'.
    Kilos are converted to lb. Grams from the variant are rounded to
    the nearest whole pound because every real SKU is a round number.
    """
    text = f"{title} {handle}"
    m = _TITLE_LB_RE.search(text)
    if m:
        try:
            return int(round(float(m.group(1))))
        except ValueError:
            pass
    m = _TITLE_KG_RE.search(text)
    if m:
        try:
            return int(round(float(m.group(1)) * 2.20462))
        except ValueError:
            pass
    # Variant-grams fallback. Shopify sometimes ships grams as an int,
    # sometimes as a string — coerce either way. 0 / missing → skip.
    grams_raw = variant.get("grams")
    try:
        grams = float(grams_raw) if grams_raw not in (None, "") else 0.0
    except (TypeError, ValueError):
        grams = 0.0
    if grams > 0:
        lb = grams / _GRAMS_PER_LB
        # Anything under ~1 lb is almost certainly apparel / an
        # accessory that leaked past the filter — don't fabricate a
        # bag size for it.
        if lb >= 1.0:
            return int(round(lb))
    return None


def _extract_tags(raw_tags: Any) -> tuple[str, ...]:
    """Shopify returns ``tags`` as either a comma-separated string
    ("merch, 20lb, lump") or as a list of strings depending on the
    store. Normalize to a lowercased tuple either way."""
    if isinstance(raw_tags, list):
        return tuple(str(t).strip().lower() for t in raw_tags if t)
    if isinstance(raw_tags, str):
        return tuple(t.strip().lower() for t in raw_tags.split(",") if t.strip())
    return ()


def _matches_filter(handle: str, title: str, tags: tuple[str, ...], cfg: dict[str, Any]) -> bool:
    low = f"{handle} {title}".lower()
    if not any(k in low for k in cfg["include_title_keywords"]):
        return False
    if any(k in low for k in cfg["exclude_title_keywords"]):
        return False
    excluded_tags = cfg.get("exclude_tags", ())
    if any(t in tags for t in excluded_tags):
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
        tags = _extract_tags(p.get("tags"))
        if not _matches_filter(handle, title, tags, cfg):
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
        category = _infer_category(title, handle)
        bag_size = _infer_bag_size_lb(title, handle, variant)
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
                category=category,
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
            existing.category = category
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
