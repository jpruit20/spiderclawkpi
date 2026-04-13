"""Amazon SP-API connector.

Pulls product catalog data (ratings, review counts, BSR), pricing,
and sales/traffic reports for Spider Grills' own seller account.
Results go into social_mentions (for reviews/ratings) and a dedicated
amazon_product_metrics table.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import SocialMention
from app.services.source_health import finish_sync_run, start_sync_run, upsert_source_config

settings = get_settings()
logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    logger.addHandler(stream_handler)

TIMEOUT_SECONDS = 30

# LWA token endpoint
LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"

# SP-API base URLs by region
SP_API_BASE = {
    "us-east-1": "https://sellingpartnerapi-na.amazon.com",
    "eu-west-1": "https://sellingpartnerapi-eu.amazon.com",
    "us-west-2": "https://sellingpartnerapi-fe.amazon.com",
}

# Token cache
_access_token: str | None = None
_token_expires: float = 0


def _configured() -> bool:
    return bool(
        settings.amazon_sp_client_id
        and settings.amazon_sp_client_secret
        and settings.amazon_sp_refresh_token
    )


def _get_access_token() -> str:
    """Get an LWA access token, refreshing if needed."""
    global _access_token, _token_expires

    if _access_token and time.time() < _token_expires - 60:
        return _access_token

    resp = requests.post(
        LWA_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": settings.amazon_sp_refresh_token,
            "client_id": settings.amazon_sp_client_id,
            "client_secret": settings.amazon_sp_client_secret,
        },
        timeout=TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    data = resp.json()
    _access_token = data["access_token"]
    _token_expires = time.time() + data.get("expires_in", 3600)
    logger.info("amazon: refreshed LWA access token")
    return _access_token


def _sp_api_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Make an authenticated GET request to SP-API."""
    token = _get_access_token()
    base = SP_API_BASE.get(settings.amazon_sp_region, SP_API_BASE["us-east-1"])
    url = f"{base}{path}"
    headers = {
        "x-amz-access-token": token,
        "Content-Type": "application/json",
    }
    resp = requests.get(url, headers=headers, params=params or {}, timeout=TIMEOUT_SECONDS)
    if resp.status_code == 429:
        # Rate limited — wait and retry once
        retry_after = float(resp.headers.get("Retry-After", "2"))
        logger.warning("amazon: rate limited, waiting %.1fs", retry_after)
        time.sleep(retry_after)
        resp = requests.get(url, headers=headers, params=params or {}, timeout=TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.json()


def _get_catalog_items(asins: list[str] | None = None) -> list[dict[str, Any]]:
    """Fetch catalog items for the seller's products.

    If ASINs not provided, uses the seller's listings to discover them.
    """
    marketplace = settings.amazon_marketplace_id

    if not asins:
        # Use search catalog to find our products
        try:
            data = _sp_api_get(
                "/catalog/2022-04-01/items",
                params={
                    "marketplaceIds": marketplace,
                    "sellerId": _extract_seller_id(),
                    "includedData": "summaries,salesRanks,attributes",
                    "pageSize": "20",
                },
            )
            return data.get("items", [])
        except Exception as exc:
            logger.warning("amazon: catalog search failed: %s", exc)
            return []

    # Fetch specific ASINs
    items = []
    for asin in asins:
        try:
            data = _sp_api_get(
                f"/catalog/2022-04-01/items/{asin}",
                params={
                    "marketplaceIds": marketplace,
                    "includedData": "summaries,salesRanks,attributes",
                },
            )
            items.append(data)
        except Exception as exc:
            logger.warning("amazon: catalog item %s failed: %s", asin, exc)
    return items


def _extract_seller_id() -> str:
    """Extract seller ID from app ID or config."""
    # Try to get from self-reported config; fallback to API
    if settings.amazon_sp_app_id:
        return settings.amazon_sp_app_id
    return ""


def _get_my_listings() -> list[dict[str, Any]]:
    """Get the seller's active listings via the Listings API or Reports API."""
    marketplace = settings.amazon_marketplace_id
    try:
        # Use catalog search with keywords as a lightweight discovery
        data = _sp_api_get(
            "/catalog/2022-04-01/items",
            params={
                "marketplaceIds": marketplace,
                "keywords": "Spider Grills",
                "includedData": "summaries,salesRanks",
                "pageSize": "20",
            },
        )
        return data.get("items", [])
    except Exception as exc:
        logger.warning("amazon: listing discovery failed: %s", exc)
        return []


COMPETITOR_SEARCHES = [
    "charcoal grill temperature controller",
    "kamado grill fan controller",
    "charcoal smoker fan controller",
    "wifi grill thermometer controller",
]


def _get_competitor_products() -> list[dict[str, Any]]:
    """Search Amazon catalog for competitor products in our categories."""
    marketplace = settings.amazon_marketplace_id
    all_items: list[dict[str, Any]] = []
    for query in COMPETITOR_SEARCHES:
        try:
            data = _sp_api_get(
                "/catalog/2022-04-01/items",
                params={
                    "marketplaceIds": marketplace,
                    "keywords": query,
                    "includedData": "summaries,salesRanks",
                    "pageSize": "10",
                },
            )
            all_items.extend(data.get("items", []))
        except Exception as exc:
            logger.warning("amazon: competitor search '%s' failed: %s", query, exc)
    # Deduplicate by ASIN
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in all_items:
        asin = item.get("asin", "")
        if asin and asin not in seen:
            seen.add(asin)
            unique.append(item)
    return unique


def _get_competitive_pricing(asin: str) -> dict[str, Any] | None:
    """Get competitive pricing for an ASIN."""
    marketplace = settings.amazon_marketplace_id
    try:
        data = _sp_api_get(
            f"/products/pricing/v0/competitivePrice",
            params={
                "MarketplaceId": marketplace,
                "Asins": asin,
                "ItemType": "Asin",
            },
        )
        return data
    except Exception as exc:
        logger.warning("amazon: pricing for %s failed: %s", asin, exc)
        return None


def _parse_catalog_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """Extract useful fields from a catalog item response."""
    asin = item.get("asin", "")
    if not asin:
        return None

    summaries = item.get("summaries", [])
    summary = summaries[0] if summaries else {}

    title = summary.get("itemName", summary.get("title", ""))
    brand = summary.get("brand", "")
    marketplace = summary.get("marketplaceId", "")

    # Rating info is sometimes in attributes
    attributes = item.get("attributes", {})

    # Sales rank
    sales_ranks = item.get("salesRanks", [])
    bsr = None
    bsr_category = None
    if sales_ranks:
        for rank_group in sales_ranks:
            classified = rank_group.get("classificationRanks", [])
            display = rank_group.get("displayGroupRanks", [])
            ranks = classified or display
            if ranks:
                bsr = ranks[0].get("rank")
                bsr_category = ranks[0].get("title", ranks[0].get("displayGroupName", ""))
                break

    return {
        "asin": asin,
        "title": title,
        "brand": brand,
        "marketplace": marketplace,
        "bsr": bsr,
        "bsr_category": bsr_category,
        "image_url": summary.get("mainImage", {}).get("link"),
    }


def sync_amazon(db: Session) -> dict[str, Any]:
    """Sync Amazon product data into social_mentions and log metrics."""
    started = time.monotonic()

    configured = _configured()
    upsert_source_config(
        db,
        "amazon",
        configured=configured,
        enabled=configured,
        sync_mode="poll",
        config_json={"source_type": "connector"},
    )
    db.commit()

    if not configured:
        return {
            "ok": False,
            "message": "Amazon SP-API not configured (AMAZON_SP_CLIENT_ID, AMAZON_SP_CLIENT_SECRET, AMAZON_SP_REFRESH_TOKEN)",
            "records_processed": 0,
        }

    run = start_sync_run(db, "amazon", "poll_catalog", {})
    db.commit()

    stats: dict[str, Any] = {
        "records_fetched": 0,
        "inserted": 0,
        "updated": 0,
        "products": [],
    }

    try:
        # Step 1: Discover our products
        items = _get_my_listings()
        stats["records_fetched"] = len(items)
        logger.info("amazon: discovered %d catalog items", len(items))

        for item in items:
            parsed = _parse_catalog_item(item)
            if not parsed:
                continue

            asin = parsed["asin"]

            # Fetch competitive pricing for this ASIN
            pricing_data = _get_competitive_pricing(asin)
            competitive_price = None
            listed_price = None
            if pricing_data:
                try:
                    products = pricing_data.get("payload", pricing_data.get("products", []))
                    if isinstance(products, list):
                        for prod in products:
                            comp_prices = prod.get("competitivePricing", {}).get("competitivePrices", [])
                            for cp in comp_prices:
                                price_obj = cp.get("price", {})
                                amt = price_obj.get("amount") or price_obj.get("landedPrice", {}).get("amount")
                                if amt:
                                    competitive_price = float(amt)
                                    break
                            offers = prod.get("offers", [])
                            if offers:
                                listing_price = offers[0].get("listingPrice", {})
                                if listing_price.get("amount"):
                                    listed_price = float(listing_price["amount"])
                except Exception as exc:
                    logger.debug("amazon: pricing parse for %s: %s", asin, exc)

            stats["products"].append({
                "asin": asin,
                "title": parsed["title"],
                "bsr": parsed["bsr"],
                "bsr_category": parsed["bsr_category"],
                "competitive_price": competitive_price,
                "listed_price": listed_price,
            })

            # Upsert into social_mentions as an amazon product record
            external_id = f"product:{asin}"
            body_parts = []
            if parsed["bsr"]:
                body_parts.append(f"BSR #{parsed['bsr']} in {parsed['bsr_category'] or 'N/A'}")
            if competitive_price:
                body_parts.append(f"Price: ${competitive_price:.2f}")
            if parsed["brand"]:
                body_parts.append(f"Brand: {parsed['brand']}")
            body = " | ".join(body_parts) if body_parts else ""

            existing = db.execute(
                select(SocialMention).where(
                    SocialMention.platform == "amazon",
                    SocialMention.external_id == external_id,
                )
            ).scalars().first()

            metadata = {
                "asin": asin,
                "bsr": parsed["bsr"],
                "bsr_category": parsed["bsr_category"],
                "brand": parsed["brand"],
                "image_url": parsed["image_url"],
                "marketplace": parsed["marketplace"],
                "data_type": "product_catalog",
                "competitive_price": competitive_price,
                "listed_price": listed_price,
            }

            if existing is None:
                mention = SocialMention(
                    platform="amazon",
                    external_id=external_id,
                    source_url=f"https://www.amazon.com/dp/{asin}",
                    title=parsed["title"],
                    body=body,
                    author=parsed["brand"] or "Spider Grills",
                    engagement_score=parsed["bsr"] or 0,
                    comment_count=0,
                    sentiment="neutral",
                    sentiment_score=0.0,
                    classification="product_listing",
                    brand_mentioned=True,
                    product_mentioned=parsed["title"][:128] if parsed["title"] else None,
                    competitor_mentioned=None,
                    trend_topic=None,
                    relevance_score=1.0,
                    published_at=datetime.now(timezone.utc),
                    metadata_json=metadata,
                )
                db.add(mention)
                stats["inserted"] += 1
            else:
                existing.title = parsed["title"]
                existing.body = body
                existing.engagement_score = parsed["bsr"] or 0
                existing.metadata_json = {**(existing.metadata_json or {}), **metadata}
                stats["updated"] += 1

        # Step 2: Discover competitor products in our categories
        competitor_items = _get_competitor_products()
        stats["competitor_products_fetched"] = len(competitor_items)
        logger.info("amazon: discovered %d competitor catalog items", len(competitor_items))

        our_asins = {p["asin"] for p in stats["products"]}
        for item in competitor_items:
            parsed = _parse_catalog_item(item)
            if not parsed:
                continue
            asin = parsed["asin"]
            if asin in our_asins:
                continue  # Skip our own products

            external_id = f"competitor:{asin}"
            brand = parsed["brand"] or "Unknown"
            body_parts = []
            if parsed["bsr"]:
                body_parts.append(f"BSR #{parsed['bsr']} in {parsed['bsr_category'] or 'N/A'}")
            if brand:
                body_parts.append(f"Brand: {brand}")
            body = " | ".join(body_parts) if body_parts else ""

            # Determine if this is a known competitor brand
            brand_lower = brand.lower()
            competitor_name = None
            for name in ["traeger", "weber", "kamado joe", "big green egg", "pit boss",
                         "camp chef", "rec tec", "masterbuilt", "flameboss", "fireboard",
                         "bbq guru", "oklahoma joe", "char-griller", "dyna-glo"]:
                if name.replace(" ", "") in brand_lower.replace(" ", "").replace("-", ""):
                    competitor_name = name.replace(" ", "_").replace("-", "_")
                    break

            existing = db.execute(
                select(SocialMention).where(
                    SocialMention.platform == "amazon",
                    SocialMention.external_id == external_id,
                )
            ).scalars().first()

            comp_metadata = {
                "asin": asin,
                "bsr": parsed["bsr"],
                "bsr_category": parsed["bsr_category"],
                "brand": brand,
                "image_url": parsed["image_url"],
                "marketplace": parsed["marketplace"],
                "data_type": "competitor_product",
            }

            if existing is None:
                mention = SocialMention(
                    platform="amazon",
                    external_id=external_id,
                    source_url=f"https://www.amazon.com/dp/{asin}",
                    title=parsed["title"],
                    body=body,
                    author=brand,
                    engagement_score=parsed["bsr"] or 0,
                    comment_count=0,
                    sentiment="neutral",
                    sentiment_score=0.0,
                    classification="competitor_product",
                    brand_mentioned=False,
                    product_mentioned=None,
                    competitor_mentioned=competitor_name,
                    trend_topic=None,
                    relevance_score=0.3,
                    published_at=datetime.now(timezone.utc),
                    metadata_json=comp_metadata,
                )
                db.add(mention)
                stats["inserted"] += 1
            else:
                existing.title = parsed["title"]
                existing.body = body
                existing.engagement_score = parsed["bsr"] or 0
                existing.competitor_mentioned = competitor_name
                existing.metadata_json = {**(existing.metadata_json or {}), **comp_metadata}
                stats["updated"] += 1

        duration_ms = int((time.monotonic() - started) * 1000)
        run.metadata_json = {**(run.metadata_json or {}), **stats, "duration_ms": duration_ms}
        finish_sync_run(db, run, status="success", records_processed=stats["inserted"] + stats["updated"])
        db.commit()

        logger.info("amazon sync complete: %d inserted, %d updated", stats["inserted"], stats["updated"])
        return {"ok": True, "records_processed": stats["inserted"] + stats["updated"], **stats, "duration_ms": duration_ms}

    except Exception as exc:
        db.rollback()
        run = db.merge(run)
        duration_ms = int((time.monotonic() - started) * 1000)
        run.metadata_json = {**(run.metadata_json or {}), **stats, "duration_ms": duration_ms}
        finish_sync_run(db, run, status="failed", error_message=str(exc))
        db.commit()
        logger.exception("amazon sync failed")
        return {"ok": False, "message": str(exc), "records_processed": 0, **stats, "duration_ms": duration_ms}
