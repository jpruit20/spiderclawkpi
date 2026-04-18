from datetime import datetime, timedelta, timezone
import logging
import time
from typing import Any, Optional
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import TWMetricCatalog, TWRawPayload, TWSummaryDaily, TWSummaryIntraday
from app.services.source_health import finish_sync_run, start_sync_run, upsert_source_config


settings = get_settings()
logger = logging.getLogger(__name__)
SUMMARY_URL = "https://api.triplewhale.com/api/v2/summary-page/get-data"
TIMEOUT_SECONDS = 45
BUSINESS_TZ = ZoneInfo("America/New_York")


def _coerce_number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").strip())
        except ValueError:
            return None
    return None


def _collect_metric_objects(node: Any, out: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        if "id" in node and "values" in node and isinstance(node.get("values"), dict):
            out.append(node)
        for value in node.values():
            _collect_metric_objects(value, out)
    elif isinstance(node, list):
        for item in node:
            _collect_metric_objects(item, out)


def _build_metric_index(raw: Any) -> dict[str, dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    _collect_metric_objects(raw, objects)
    result: dict[str, dict[str, Any]] = {}
    for metric in objects:
        metric_id = metric.get("id")
        if isinstance(metric_id, str):
            result[metric_id] = metric
    return result


def _current_value(index: dict[str, dict[str, Any]], metric_id: str, default: float = 0.0) -> float:
    metric = index.get(metric_id)
    if not metric:
        return default
    values = metric.get("values") or {}
    parsed = _coerce_number(values.get("current")) if isinstance(values, dict) else None
    return parsed if parsed is not None else default


def _sum_current_values(index: dict[str, dict[str, Any]], metric_ids: list[str]) -> float:
    return sum(_current_value(index, metric_id, 0.0) for metric_id in metric_ids)


# Per-channel spend metric IDs — TW surfaces spend under multiple
# aliases depending on the channel / integration era (e.g. pinterestAds
# vs pinterestSpend, googleAds vs googleSpend). We sum across aliases
# for each normalized channel so the total lands in one column.
# ``custom_spend`` captures the two meta-channels TW uses for arbitrary
# user-defined integrations so those dollars aren't lost.
CHANNEL_SPEND_IDS: dict[str, list[str]] = {
    "facebook_spend": ["facebookSpend", "facebookAds"],
    "google_spend": ["googleSpend", "googleAds"],
    "tiktok_spend": ["tiktokSpend", "tiktokAds"],
    "snapchat_spend": ["snapchatSpend", "snapchatAds"],
    "pinterest_spend": ["pinterestSpend", "pinterestAds"],
    "bing_spend": ["bingAdSpend", "bingSpend", "bingAds"],
    "twitter_spend": ["twitterAds", "twitterSpend"],
    "reddit_spend": ["redditSpend", "redditAds"],
    "linkedin_spend": ["linkedinSpend", "linkedinAds"],
    "amazon_ads_spend": ["amazonAds", "amazonSpend"],
    "smsbump_spend": ["smsbumpSpend"],
    "omnisend_spend": ["omnisendSpend"],
    "postscript_spend": ["postscriptSpend"],
    "taboola_spend": ["taboolaSpend"],
    "outbrain_spend": ["outbrainSpend"],
    "stackadapt_spend": ["stackadaptSpend"],
    "adroll_spend": ["adrollSpend"],
    "impact_spend": ["impactSpend"],
    "custom_spend": ["totalCustomAdSpends", "totalApiCustomAdSpends"],
}


def _all_channel_metric_ids() -> list[str]:
    return [mid for ids in CHANNEL_SPEND_IDS.values() for mid in ids]


def _build_payload(store: str, start_date: str, end_date: str) -> dict[str, Any]:
    return {
        "period": {"start": start_date, "end": end_date},
        "timezone": "America/New_York",
        "todayHour": 23,
        "shopDomain": store,
        "panel": "summary",
        "metrics": [
            "pixelVisitors",
            "pixelUniqueVisitors",
            "pixelConversionRate",
            "pixelPercentAtc",
            "pixelPurchases",
            "pixelPageViews",
            "pixelBounceRate",
            "pixelCostPerSession",
            "pixelCostPerAtc",
            "blendedSales",
            "blendedAdSpend",
            # Per-channel spend — stored as first-class columns so we
            # can chart spend mix without re-parsing raw payloads.
            *_all_channel_metric_ids(),
        ],
    }


def _extract_channel_spends(index: dict[str, dict[str, Any]]) -> dict[str, float]:
    """Return {column_name: spend} for every channel defined in CHANNEL_SPEND_IDS.

    Each channel sums across all known aliases for that channel, since
    TW can emit spend under a historical or current alias depending on
    when the ad-account was connected.
    """
    out: dict[str, float] = {}
    for column_name, aliases in CHANNEL_SPEND_IDS.items():
        out[column_name] = round(_sum_current_values(index, aliases), 2)
    return out


def _normalize(raw: Any, payload: dict[str, Any]) -> dict[str, Any]:
    index = _build_metric_index(raw)
    channel_spends = _extract_channel_spends(index)
    # Blended ad spend: prefer TW's blended value, else reconstruct by
    # summing the per-channel totals (not the raw aliases — we already
    # collapsed aliases in ``channel_spends``).
    ad_spend = _current_value(index, "blendedAdSpend", 0.0)
    if ad_spend == 0.0:
        ad_spend = sum(channel_spends.values())

    # Channel-metrics catch-all: stash the raw per-channel metric values
    # the payload exposed (keyed by alias) so we can re-derive ROAS /
    # revenue / orders per channel later without a new migration.
    channel_metrics_raw = {
        mid: _current_value(index, mid, 0.0)
        for mid in _all_channel_metric_ids()
        if mid in index
    }

    return {
        "date": payload["period"]["end"],
        "start_date": payload["period"]["start"],
        "end_date": payload["period"]["end"],
        "sessions": round(_current_value(index, "pixelVisitors", 0.0), 2),
        "users": round(_current_value(index, "pixelUniqueVisitors", 0.0), 2),
        "conversion_rate": round(_current_value(index, "pixelConversionRate", 0.0), 6),
        "add_to_cart_rate": round(_current_value(index, "pixelPercentAtc", 0.0), 6),
        "purchases": round(_current_value(index, "pixelPurchases", 0.0), 2),
        "page_views": round(_current_value(index, "pixelPageViews", 0.0), 2),
        "bounce_rate": round(_current_value(index, "pixelBounceRate", 0.0), 6),
        "cost_per_session": round(_current_value(index, "pixelCostPerSession", 0.0), 4),
        "cost_per_atc": round(_current_value(index, "pixelCostPerAtc", 0.0), 4),
        "revenue": round(_current_value(index, "blendedSales", 0.0), 2),
        "ad_spend": round(ad_spend, 2),
        **channel_spends,
        "channel_metrics_json": channel_metrics_raw,
        "metric_ids_found": sorted(index.keys()),
    }


# Scalar summary columns shared by TWSummaryDaily and TWSummaryIntraday.
# Listed explicitly (not derived from the model) so a new keyword in
# ``normalized`` doesn't silently land on the row — forces a deliberate
# edit here, which also forces a matching alembic migration.
_SUMMARY_SCALAR_FIELDS = (
    "sessions", "users", "conversion_rate", "add_to_cart_rate",
    "purchases", "page_views", "bounce_rate", "cost_per_session",
    "cost_per_atc", "revenue", "ad_spend",
    "facebook_spend", "google_spend", "tiktok_spend", "snapchat_spend",
    "pinterest_spend", "bing_spend", "twitter_spend", "reddit_spend",
    "linkedin_spend", "amazon_ads_spend", "smsbump_spend", "omnisend_spend",
    "postscript_spend", "taboola_spend", "outbrain_spend", "stackadapt_spend",
    "adroll_spend", "impact_spend", "custom_spend",
)


def _apply_summary_fields(record: Any, normalized: dict[str, Any]) -> None:
    for field in _SUMMARY_SCALAR_FIELDS:
        setattr(record, field, normalized.get(field, 0.0))
    record.channel_metrics_json = normalized.get("channel_metrics_json") or {}


def sync_triplewhale(db: Session, backfill_days: int | None = None) -> dict[str, Any]:
    started = time.monotonic()
    configured = bool(settings.triplewhale_api_key and settings.shopify_store_url)
    upsert_source_config(
        db,
        "triplewhale",
        configured=configured,
        sync_mode="poll",
        config_json={"shop_domain": settings.shopify_store_url, "summary_url": SUMMARY_URL},
    )
    db.commit()

    if not configured:
        return {"ok": False, "message": "Triple Whale not configured", "records_processed": 0}

    days = max(1, backfill_days or settings.backfill_days)
    run = start_sync_run(db, "triplewhale", "backfill_daily", {"days": days})
    db.commit()

    headers = {
        "x-api-key": settings.triplewhale_api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    stats = {
        "records_fetched": 0,
        "records_inserted": 0,
        "records_updated": 0,
        "duplicates_skipped": 0,
    }
    processed = 0
    last_payload: dict[str, Any] | None = None
    try:
        business_today = datetime.now(BUSINESS_TZ).date()
        current_hour_bucket = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

        for day_offset in range(days):
            target_date = business_today - timedelta(days=day_offset)
            payload = _build_payload(
                settings.shopify_store_url,
                target_date.isoformat(),
                target_date.isoformat(),
            )
            last_payload = payload
            logger.info("triplewhale request payload", extra={"payload": payload})
            response = requests.post(SUMMARY_URL, headers=headers, json=payload, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
            raw = response.json()
            normalized = _normalize(raw, payload)
            stats["records_fetched"] += 1

            raw_payload = db.execute(
                select(TWRawPayload).where(TWRawPayload.business_date == target_date)
            ).scalars().first()
            if raw_payload is None:
                raw_payload = TWRawPayload(business_date=target_date)
                db.add(raw_payload)
                stats["records_inserted"] += 1
            else:
                stats["records_updated"] += 1
            raw_payload.request_payload = payload
            raw_payload.response_payload = raw
            raw_payload.source_run_id = run.id

            record = db.execute(
                select(TWSummaryDaily).where(TWSummaryDaily.business_date == target_date)
            ).scalars().first()
            if record is None:
                record = TWSummaryDaily(business_date=target_date)
                db.add(record)
            _apply_summary_fields(record, normalized)

            bucket = current_hour_bucket if target_date == business_today else datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
            intraday = db.execute(
                select(TWSummaryIntraday).where(TWSummaryIntraday.bucket_start == bucket)
            ).scalars().first()
            if intraday is None:
                intraday = TWSummaryIntraday(bucket_start=bucket)
                db.add(intraday)
            _apply_summary_fields(intraday, normalized)

            for metric_id in set(normalized["metric_ids_found"]):
                catalog = db.execute(select(TWMetricCatalog).where(TWMetricCatalog.metric_id == metric_id)).scalars().first()
                if catalog is None:
                    db.add(TWMetricCatalog(metric_id=metric_id, metadata_json={"source": "summary-page"}))
                    db.flush()
                else:
                    stats["duplicates_skipped"] += 1

            processed += 1

        duration_ms = int((time.monotonic() - started) * 1000)
        run.metadata_json = {**run.metadata_json, **stats, "duration_ms": duration_ms, "last_payload": last_payload}
        finish_sync_run(db, run, status="success", records_processed=processed)
        db.commit()
        logger.info("triplewhale sync complete", extra={"stats": stats, "duration_ms": duration_ms, "payload": last_payload})
        return {"ok": True, "records_processed": processed, **stats, "duration_ms": duration_ms, "last_payload": last_payload}
    except Exception as exc:
        db.rollback()
        run = db.merge(run)
        duration_ms = int((time.monotonic() - started) * 1000)
        run.metadata_json = {**(run.metadata_json or {}), **stats, "duration_ms": duration_ms, "last_payload": last_payload}
        finish_sync_run(db, run, status="failed", error_message=str(exc), records_processed=processed)
        db.commit()
        logger.exception("triplewhale sync failed")
        return {"ok": False, "message": str(exc), "records_processed": processed, **stats, "duration_ms": duration_ms, "last_payload": last_payload}
