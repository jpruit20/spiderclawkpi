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
        ],
    }


def _normalize(raw: Any, payload: dict[str, Any]) -> dict[str, Any]:
    index = _build_metric_index(raw)
    ad_spend = _current_value(index, "blendedAdSpend", 0.0)
    if ad_spend == 0.0:
        ad_spend = _sum_current_values(
            index,
            [
                "facebookSpend",
                "googleAds",
                "googleSpend",
                "tiktokSpend",
                "snapchatSpend",
                "pinterestAds",
                "pinterestSpend",
                "bingAdSpend",
                "twitterAds",
                "redditSpend",
                "linkedinSpend",
                "taboolaSpend",
                "outbrainSpend",
                "stackadaptSpend",
                "adrollSpend",
                "impactSpend",
                "amazonAds",
                "smsbumpSpend",
                "omnisendSpend",
                "postscriptSpend",
                "totalCustomAdSpends",
                "totalApiCustomAdSpends",
            ],
        )

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
        "metric_ids_found": sorted(index.keys()),
    }


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
            record.sessions = normalized["sessions"]
            record.users = normalized["users"]
            record.conversion_rate = normalized["conversion_rate"]
            record.add_to_cart_rate = normalized["add_to_cart_rate"]
            record.purchases = normalized["purchases"]
            record.page_views = normalized["page_views"]
            record.bounce_rate = normalized["bounce_rate"]
            record.cost_per_session = normalized["cost_per_session"]
            record.cost_per_atc = normalized["cost_per_atc"]
            record.revenue = normalized["revenue"]
            record.ad_spend = normalized["ad_spend"]

            bucket = current_hour_bucket if target_date == business_today else datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
            intraday = db.execute(
                select(TWSummaryIntraday).where(TWSummaryIntraday.bucket_start == bucket)
            ).scalars().first()
            if intraday is None:
                intraday = TWSummaryIntraday(bucket_start=bucket)
                db.add(intraday)
            intraday.sessions = normalized["sessions"]
            intraday.users = normalized["users"]
            intraday.conversion_rate = normalized["conversion_rate"]
            intraday.add_to_cart_rate = normalized["add_to_cart_rate"]
            intraday.purchases = normalized["purchases"]
            intraday.page_views = normalized["page_views"]
            intraday.bounce_rate = normalized["bounce_rate"]
            intraday.cost_per_session = normalized["cost_per_session"]
            intraday.cost_per_atc = normalized["cost_per_atc"]
            intraday.revenue = normalized["revenue"]
            intraday.ad_spend = normalized["ad_spend"]

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
        failed_run = start_sync_run(db, "triplewhale", "backfill_daily_failed", {"days": days, **stats, "last_payload": last_payload})
        duration_ms = int((time.monotonic() - started) * 1000)
        failed_run.metadata_json = {**failed_run.metadata_json, **stats, "duration_ms": duration_ms, "last_payload": last_payload}
        finish_sync_run(db, failed_run, status="failed", error_message=str(exc), records_processed=processed)
        db.commit()
        logger.exception("triplewhale sync failed")
        return {"ok": False, "message": str(exc), "records_processed": processed, **stats, "duration_ms": duration_ms, "last_payload": last_payload}
