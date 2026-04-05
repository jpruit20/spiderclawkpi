import base64
import hashlib
import hmac
import logging
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
from zoneinfo import ZoneInfo

import requests
from requests.utils import parse_header_links
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ShopifyAnalyticsDaily, ShopifyAnalyticsIntraday, ShopifyOrderDaily, ShopifyOrderEvent
from app.services.source_health import finish_sync_run, start_sync_run, upsert_source_config


settings = get_settings()
logger = logging.getLogger(__name__)
API_VERSION = settings.shopify_api_version
MAX_RETRIES = 5
TIMEOUT_SECONDS = 30
TOKEN_REFRESH_SKEW_SECONDS = 60
BUSINESS_TZ = ZoneInfo("America/New_York")


_token_cache: dict[str, Any] = {
    "access_token": None,
    "expires_at": 0,
}


def verify_shopify_hmac(raw_body: bytes, hmac_header: str | None) -> bool:
    secret = settings.shopify_webhook_secret
    if not secret or not hmac_header:
        return False
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    encoded = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(encoded, hmac_header)


def _normalize_shop_domain(raw_value: str | None) -> str:
    if not raw_value:
        raise RuntimeError("SHOPIFY_STORE_URL is not configured")
    cleaned = str(raw_value).strip()
    cleaned = cleaned.removeprefix("https://").removeprefix("http://")
    return cleaned.strip("/")


def _request_access_token() -> str:
    if settings.shopify_admin_access_token:
        return settings.shopify_admin_access_token

    client_id = settings.shopify_api_key
    client_secret = settings.shopify_api_secret
    if not client_id or not client_secret:
        raise RuntimeError(
            "Set SHOPIFY_ADMIN_ACCESS_TOKEN or both SHOPIFY_API_KEY and SHOPIFY_API_SECRET"
        )

    now = int(time.time())
    cached_token = _token_cache.get("access_token")
    cached_expires_at = int(_token_cache.get("expires_at") or 0)
    if cached_token and now < (cached_expires_at - TOKEN_REFRESH_SKEW_SECONDS):
        return str(cached_token)

    shop_domain = _normalize_shop_domain(settings.shopify_store_url)
    response = requests.post(
        f"https://{shop_domain}/admin/oauth/access_token",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    payload = response.json()
    access_token = payload.get("access_token")
    expires_in = int(payload.get("expires_in") or 86399)
    if not access_token:
        raise RuntimeError("Shopify token response did not include access_token")

    _token_cache["access_token"] = access_token
    _token_cache["expires_at"] = now + expires_in
    return str(access_token)


def build_session() -> requests.Session:
    access_token = _request_access_token()
    session = requests.Session()
    session.headers.update(
        {
            "X-Shopify-Access-Token": access_token,
            "Accept": "application/json",
        }
    )
    return session


def _parse_datetime(value: str) -> datetime:
    clean = value.strip()
    if clean.endswith("Z"):
        clean = clean[:-1] + "+00:00"
    return datetime.fromisoformat(clean)


def _business_date_from_dt(value: datetime) -> datetime.date:
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(BUSINESS_TZ).date()


def _extract_next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    normalized = link_header.replace(">,<", ",<")
    for link in parse_header_links(normalized):
        if link.get("rel") == "next":
            return link.get("url")
    return None


def _to_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def _extract_financials(order: dict[str, Any]) -> dict[str, Any]:
    total_price = _to_decimal(order.get("total_price"))
    current_total_price = _to_decimal(order.get("current_total_price") or order.get("total_price"))
    cancelled_at = order.get("cancelled_at")
    financial_status = str(order.get("financial_status") or "").lower() or None
    refunds = total_price - current_total_price
    if refunds < Decimal("0.00"):
        refunds = Decimal("0.00")

    recognized_statuses = {"paid", "partially_paid", "partially_refunded", "refunded", "authorized"}
    order_counts = cancelled_at is None and (financial_status in recognized_statuses if financial_status else True)
    recognized_revenue = Decimal("0.00") if cancelled_at else current_total_price

    return {
        "financial_status": financial_status,
        "cancelled_at": cancelled_at,
        "gross_revenue": float(total_price),
        "recognized_revenue": float(recognized_revenue),
        "refunds": float(refunds),
        "counts_as_order": order_counts,
    }


def _get_retry_delay(response: Optional[requests.Response], attempt: int) -> int:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(1, int(float(retry_after)))
            except ValueError:
                pass
    return max(1, attempt * 2)


def _request_json(session: requests.Session, url: str, params: Optional[dict[str, str]] = None) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        response: requests.Response | None = None
        try:
            response = session.get(url, params=params, timeout=TIMEOUT_SECONDS)
            if response.status_code in {429, 500, 502, 503, 504}:
                delay = _get_retry_delay(response, attempt)
                if attempt == MAX_RETRIES:
                    response.raise_for_status()
                time.sleep(delay)
                continue
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt == MAX_RETRIES:
                break
            time.sleep(_get_retry_delay(response, attempt))
    raise RuntimeError(f"Shopify request failed after {MAX_RETRIES} attempts: {last_error}")


def _latest_event(db: Session, event_type: str, order_id: str) -> ShopifyOrderEvent | None:
    return db.execute(
        select(ShopifyOrderEvent)
        .where(
            ShopifyOrderEvent.event_type == event_type,
            ShopifyOrderEvent.order_id == order_id,
        )
        .order_by(ShopifyOrderEvent.event_timestamp.desc().nullslast(), ShopifyOrderEvent.id.desc())
        .limit(1)
    ).scalars().first()


def _event_by_delivery_id(db: Session, delivery_id: str) -> ShopifyOrderEvent | None:
    return db.execute(
        select(ShopifyOrderEvent).where(ShopifyOrderEvent.delivery_id == delivery_id).limit(1)
    ).scalars().first()


def _latest_order_state(db: Session, order_id: str) -> ShopifyOrderEvent | None:
    return db.execute(
        select(ShopifyOrderEvent)
        .where(ShopifyOrderEvent.order_id == order_id)
        .order_by(ShopifyOrderEvent.event_timestamp.desc().nullslast(), ShopifyOrderEvent.id.desc())
        .limit(1)
    ).scalars().first()


def _normalized_payload_from_order(order: dict[str, Any], financials: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": order.get("id"),
        "created_at": order.get("created_at"),
        "updated_at": order.get("updated_at"),
        "processed_at": order.get("processed_at"),
        "total_price": order.get("total_price"),
        "current_total_price": order.get("current_total_price"),
        "financial_status": order.get("financial_status"),
        "cancelled_at": order.get("cancelled_at"),
        "recognized_revenue": financials["recognized_revenue"],
        "refunds": financials["refunds"],
        "counts_as_order": financials["counts_as_order"],
        "customer_id": ((order.get("customer") or {}).get("id")),
    }


def _fetch_order_by_id(order_id: str) -> dict[str, Any] | None:
    session = build_session()
    shop_domain = _normalize_shop_domain(settings.shopify_store_url)
    endpoint = f"https://{shop_domain}/admin/api/{API_VERSION}/orders/{order_id}.json"
    response = _request_json(session, endpoint, params={
        "fields": "id,created_at,updated_at,processed_at,total_price,current_total_price,financial_status,cancelled_at,customer.id"
    })
    payload = response.json()
    return payload.get("order")


def _extract_order_id_for_topic(topic: str, payload: dict[str, Any]) -> str | None:
    if payload.get("id") is not None and topic.startswith("orders/"):
        return str(payload.get("id"))
    if payload.get("order_id") is not None:
        return str(payload.get("order_id"))
    order = payload.get("order") or {}
    if isinstance(order, dict) and order.get("id") is not None:
        return str(order.get("id"))
    return str(payload.get("id")) if payload.get("id") is not None else None


def _canonicalize_webhook_payload(topic: str, payload: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    order_id = _extract_order_id_for_topic(topic, payload)
    if not order_id:
        return None, payload
    if topic.startswith("orders/"):
        return order_id, payload
    try:
        canonical = _fetch_order_by_id(order_id)
        if canonical:
            return order_id, canonical
    except Exception:
        logger.exception("shopify webhook canonical fetch failed", extra={"topic": topic, "order_id": order_id})
    return order_id, payload


def _event_timestamp_from_payload(payload: dict[str, Any]) -> datetime | None:
    for key in ("updated_at", "processed_at", "created_at"):
        value = payload.get(key)
        if value:
            return _parse_datetime(str(value))
    return None


def rebuild_shopify_daily_from_events(db: Session, business_dates: set[datetime.date]) -> int:
    if not business_dates:
        return 0

    order_ids = {
        row.order_id
        for row in db.execute(
            select(ShopifyOrderEvent)
            .where(ShopifyOrderEvent.business_date.in_(business_dates))
        ).scalars().all()
        if row.order_id
    }

    daily: dict[datetime.date, dict[str, float]] = {d: {"orders": 0, "revenue": 0.0, "refunds": 0.0} for d in business_dates}
    for order_id in order_ids:
        latest = _latest_order_state(db, order_id)
        if latest is None:
            continue
        payload = latest.normalized_payload or {}
        created_at = payload.get("created_at")
        if not created_at:
            continue
        order_dt = _parse_datetime(str(created_at))
        business_date = _business_date_from_dt(order_dt)
        if business_date not in business_dates:
            continue
        if business_date not in daily:
            daily[business_date] = {"orders": 0, "revenue": 0.0, "refunds": 0.0}
        if payload.get("counts_as_order"):
            daily[business_date]["orders"] += 1
        daily[business_date]["revenue"] += float(payload.get("recognized_revenue") or payload.get("current_total_price") or payload.get("total_price") or 0.0)
        daily[business_date]["refunds"] += float(payload.get("refunds") or 0.0)

    for business_date in business_dates:
        record = db.execute(select(ShopifyOrderDaily).where(ShopifyOrderDaily.business_date == business_date)).scalars().first()
        values = daily.get(business_date, {"orders": 0, "revenue": 0.0, "refunds": 0.0})
        if record is None:
            record = ShopifyOrderDaily(business_date=business_date)
            db.add(record)
        record.orders = int(values["orders"])
        record.revenue = float(values["revenue"])
        record.refunds = float(values["refunds"])
        record.average_order_value = (record.revenue / record.orders) if record.orders else 0.0
    db.commit()
    return len(business_dates)


def store_webhook_event(db: Session, topic: str, payload: dict[str, Any], delivery_id: str | None = None) -> ShopifyOrderEvent:
    if delivery_id:
        existing_delivery = _event_by_delivery_id(db, delivery_id)
        if existing_delivery is not None:
            return existing_delivery
    order_id, canonical_payload = _canonicalize_webhook_payload(topic, payload)
    event_ts = _event_timestamp_from_payload(canonical_payload) or _event_timestamp_from_payload(payload)
    if order_id:
        existing = _latest_event(db, topic, order_id)
        if existing and existing.event_timestamp == event_ts and existing.raw_payload == payload:
            existing.raw_payload = payload
            financials = _extract_financials(canonical_payload)
            existing.normalized_payload = _normalized_payload_from_order(canonical_payload, financials)
            existing.business_date = _business_date_from_dt(event_ts) if event_ts else existing.business_date
            db.commit()
            db.refresh(existing)
            return existing
    financials = _extract_financials(canonical_payload)
    event = ShopifyOrderEvent(
        delivery_id=delivery_id,
        event_type=topic,
        order_id=order_id,
        event_timestamp=event_ts,
        business_date=_business_date_from_dt(event_ts) if event_ts else None,
        raw_payload=payload,
        normalized_payload=_normalized_payload_from_order(canonical_payload, financials),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def sync_shopify_orders(db: Session, hours: int = 48) -> dict[str, Any]:
    started = time.monotonic()
    configured = bool(
        settings.shopify_store_url
        and (
            settings.shopify_admin_access_token
            or (settings.shopify_api_key and settings.shopify_api_secret)
        )
    )
    upsert_source_config(
        db,
        "shopify",
        configured=configured,
        sync_mode="poll+webhook",
        config_json={"store_url": settings.shopify_store_url},
    )
    db.commit()

    if not configured:
        return {"ok": False, "message": "Shopify not configured", "records_processed": 0}

    run = start_sync_run(db, "shopify", "poll_recent", {"hours": hours})
    db.commit()

    stats = {
        "records_fetched": 0,
        "records_inserted": 0,
        "records_updated": 0,
        "duplicates_skipped": 0,
    }

    try:
        session = build_session()
        shop_domain = _normalize_shop_domain(settings.shopify_store_url)
        endpoint = f"https://{shop_domain}/admin/api/{API_VERSION}/orders.json"
        window_start_utc = (datetime.now(timezone.utc) - timedelta(hours=hours)).replace(microsecond=0)
        if hours >= 24:
            business_window_start = window_start_utc.astimezone(BUSINESS_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
            created_at_min = business_window_start.astimezone(timezone.utc).isoformat()
        else:
            created_at_min = window_start_utc.isoformat()
        params = {
            "status": "any",
            "limit": "250",
            "order": "created_at asc",
            "created_at_min": created_at_min,
            "fields": "id,created_at,updated_at,total_price,current_total_price,financial_status,cancelled_at,customer.id",
        }

        all_orders: list[dict[str, Any]] = []
        seen_ids: set[Any] = set()
        next_url: str | None = endpoint
        next_params: Optional[dict[str, str]] = params

        while next_url:
            response = _request_json(session, next_url, params=next_params)
            payload = response.json()
            batch_orders = payload.get("orders", [])
            stats["records_fetched"] += len(batch_orders)
            for order in batch_orders:
                order_id = order.get("id")
                if order_id in seen_ids:
                    stats["duplicates_skipped"] += 1
                    continue
                seen_ids.add(order_id)
                all_orders.append(order)
            next_url = _extract_next_link(response.headers.get("Link"))
            next_params = None

        updated_at_min = window_start_utc.isoformat()
        updated_params = {
            "status": "any",
            "limit": "250",
            "order": "updated_at asc",
            "updated_at_min": updated_at_min,
            "fields": "id,created_at,updated_at,total_price,current_total_price,financial_status,cancelled_at,customer.id",
        }
        next_url = endpoint
        next_params = updated_params
        while next_url:
            response = _request_json(session, next_url, params=next_params)
            payload = response.json()
            batch_orders = payload.get("orders", [])
            stats["records_fetched"] += len(batch_orders)
            for order in batch_orders:
                order_id = order.get("id")
                if order_id in seen_ids:
                    continue
                seen_ids.add(order_id)
                all_orders.append(order)
            next_url = _extract_next_link(response.headers.get("Link"))
            next_params = None

        daily: dict[datetime.date, dict[str, float]] = {}
        latest_order_timestamp: datetime | None = None
        for order in all_orders:
            created_at = order.get("created_at")
            if not created_at:
                continue
            order_dt = _parse_datetime(str(created_at))
            latest_order_timestamp = max(latest_order_timestamp, order_dt) if latest_order_timestamp else order_dt
            business_date = _business_date_from_dt(order_dt)
            if business_date not in daily:
                daily[business_date] = {"orders": 0, "revenue": 0.0, "refunds": 0.0, "gross_revenue": 0.0}

            financials = _extract_financials(order)
            if financials["counts_as_order"]:
                daily[business_date]["orders"] += 1
            daily[business_date]["revenue"] += float(financials["recognized_revenue"])
            daily[business_date]["refunds"] += float(financials["refunds"])
            daily[business_date]["gross_revenue"] += float(financials["gross_revenue"])

            order_id = str(order.get("id"))
            event_record = _latest_event(db, "poll.order_snapshot", order_id)
            updated_at = _parse_datetime(str(order.get("updated_at") or order.get("created_at")))
            normalized_payload = {
                **_normalized_payload_from_order(order, financials)
            }
            if event_record is None:
                db.add(
                    ShopifyOrderEvent(
                        event_type="poll.order_snapshot",
                        order_id=order_id,
                        event_timestamp=updated_at,
                        business_date=business_date,
                        raw_payload=order,
                        normalized_payload=normalized_payload,
                    )
                )
                stats["records_inserted"] += 1
            else:
                event_record.event_timestamp = updated_at
                event_record.business_date = business_date
                event_record.raw_payload = order
                event_record.normalized_payload = normalized_payload
                stats["records_updated"] += 1

        for business_date, values in daily.items():
            record = db.execute(
                select(ShopifyOrderDaily).where(ShopifyOrderDaily.business_date == business_date)
            ).scalars().first()
            if record is None:
                record = ShopifyOrderDaily(business_date=business_date)
                db.add(record)
            record.orders = int(values["orders"])
            record.revenue = float(values["revenue"])
            record.refunds = float(values.get("refunds") or 0.0)
            record.average_order_value = (record.revenue / record.orders) if record.orders else 0.0
            record.source_run_id = run.id

        if latest_order_timestamp is None:
            latest_order_timestamp = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        bucket_start = latest_order_timestamp.replace(minute=0, second=0, microsecond=0)
        intraday = db.execute(
            select(ShopifyAnalyticsIntraday).where(ShopifyAnalyticsIntraday.bucket_start == bucket_start)
        ).scalars().first()
        if intraday is None:
            intraday = ShopifyAnalyticsIntraday(bucket_start=bucket_start)
            db.add(intraday)
        latest_day = _business_date_from_dt(latest_order_timestamp)
        latest_revenue = daily.get(latest_day, {"revenue": 0.0})["revenue"]
        intraday.sessions = max(float(intraday.sessions or 0.0), 0.0)
        intraday.users = max(float(intraday.users or 0.0), 0.0)
        intraday.conversion_rate = max(float(intraday.conversion_rate or 0.0), 0.0)
        intraday.revenue = max(float(intraday.revenue or 0.0), float(latest_revenue or 0.0))

        duration_ms = int((time.monotonic() - started) * 1000)
        run.metadata_json = {**run.metadata_json, **stats, "duration_ms": duration_ms}
        finish_sync_run(db, run, status="success", records_processed=len(all_orders))
        db.commit()
        logger.info("shopify sync complete", extra={"stats": stats, "duration_ms": duration_ms})
        return {
            "ok": True,
            "records_processed": len(all_orders),
            "business_dates": len(daily),
            **stats,
            "duration_ms": duration_ms,
        }
    except Exception as exc:
        db.rollback()
        run = db.merge(run)
        duration_ms = int((time.monotonic() - started) * 1000)
        run.metadata_json = {**(run.metadata_json or {}), **stats, "duration_ms": duration_ms}
        finish_sync_run(db, run, status="failed", error_message=str(exc))
        db.commit()
        logger.exception("shopify sync failed")
        return {"ok": False, "message": str(exc), "records_processed": 0, **stats, "duration_ms": duration_ms}
