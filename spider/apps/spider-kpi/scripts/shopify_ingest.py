#!/usr/bin/env python3
import json
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Set

import requests
from requests.utils import parse_header_links


BASE_DIR = Path("/home/jpruit20/.openclaw/workspace/spider-kpi")
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "ingest.log"
ORDERS_DAILY_FILE = PROCESSED_DIR / "orders_daily.json"
API_VERSION = "2024-10"
MAX_RETRIES = 5
BACKOFF_SECONDS = 2
TIMEOUT_SECONDS = 30


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stdout),
        ],
    )


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def build_session(api_key: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "X-Shopify-Access-Token": api_key,
            "Accept": "application/json",
        }
    )
    return session


def get_retry_delay_seconds(response: requests.Response, attempt: int) -> int:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return max(1, int(float(retry_after)))
        except ValueError:
            logging.warning("Invalid Retry-After header value: %s", retry_after)
    return BACKOFF_SECONDS * attempt


def request_with_retries(
    session: requests.Session,
    method: str,
    url: str,
    params: Optional[Dict[str, str]] = None,
) -> requests.Response:
    last_error: Optional[Exception] = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.request(method, url, params=params, timeout=TIMEOUT_SECONDS)

            if response.status_code in {429, 500, 502, 503, 504}:
                delay = get_retry_delay_seconds(response, attempt)
                logging.warning(
                    "Transient Shopify error %s on attempt %s/%s. Retrying in %ss.",
                    response.status_code,
                    attempt,
                    MAX_RETRIES,
                    delay,
                )
                time.sleep(delay)
                continue

            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt == MAX_RETRIES:
                break
            delay = BACKOFF_SECONDS * attempt
            logging.warning(
                "Request failed on attempt %s/%s: %s. Retrying in %ss.",
                attempt,
                MAX_RETRIES,
                exc,
                delay,
            )
            time.sleep(delay)

    raise RuntimeError(f"Shopify request failed after {MAX_RETRIES} attempts: {last_error}")


def extract_next_link(link_header: Optional[str]) -> Optional[str]:
    if not link_header:
        return None

    normalized_header = link_header.replace(">,<", ",<")
    for link in parse_header_links(normalized_header):
        if link.get("rel") == "next":
            return link.get("url")
    return None


def parse_shopify_datetime(value: str) -> datetime:
    normalized_value = value.strip()
    if normalized_value.endswith("Z"):
        normalized_value = normalized_value[:-1] + "+00:00"
    return datetime.fromisoformat(normalized_value)


def fetch_orders(session: requests.Session, store_url: str, created_at_min: str) -> List[Dict[str, object]]:
    endpoint = f"https://{store_url}/admin/api/{API_VERSION}/orders.json"
    params = {
        "status": "any",
        "limit": "250",
        "order": "created_at asc",
        "created_at_min": created_at_min,
        "fields": "id,created_at,total_price,customer.id",
    }

    all_orders: List[Dict[str, object]] = []
    seen_order_ids: Set[object] = set()
    next_url: Optional[str] = endpoint
    next_params: Optional[Dict[str, str]] = params

    while next_url:
        response = request_with_retries(session, "GET", next_url, params=next_params)
        payload = response.json()
        batch = payload.get("orders", [])

        new_orders = 0
        for order in batch:
            order_id = order.get("id")
            if order_id in seen_order_ids:
                continue
            seen_order_ids.add(order_id)
            all_orders.append(order)
            new_orders += 1

        logging.info(
            "Fetched %s orders from Shopify, %s unique orders kept.",
            len(batch),
            new_orders,
        )

        next_url = extract_next_link(response.headers.get("Link"))
        next_params = None

    return all_orders


def simplify_orders(orders: List[Dict[str, object]]) -> List[Dict[str, object]]:
    simplified_orders: List[Dict[str, object]] = []

    for order in orders:
        customer = order.get("customer") or {}
        if not isinstance(customer, dict):
            customer = {}

        simplified_orders.append(
            {
                "order_id": order.get("id"),
                "created_at": order.get("created_at"),
                "total_price": order.get("total_price"),
                "customer_id": customer.get("id"),
            }
        )

    return simplified_orders


def write_raw_orders(simplified_orders: List[Dict[str, object]]) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = RAW_DIR / f"orders_{timestamp}.json"

    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(simplified_orders, handle, indent=2)

    logging.info("Wrote raw orders to %s", output_path)
    return output_path


def normalize_orders(simplified_orders: List[Dict[str, object]]) -> List[Dict[str, object]]:
    daily_totals: Dict[str, Dict[str, object]] = defaultdict(
        lambda: {"orders": 0, "revenue": Decimal("0.00")}
    )

    for order in simplified_orders:
        created_at = order.get("created_at")
        if not created_at:
            logging.warning("Skipping order without created_at: %s", order)
            continue

        try:
            order_datetime = parse_shopify_datetime(str(created_at))
        except ValueError:
            logging.warning("Skipping order with invalid created_at: %s", created_at)
            continue

        total_price = order.get("total_price", 0)
        try:
            revenue = Decimal(str(total_price))
        except (InvalidOperation, ValueError):
            logging.warning("Invalid total_price for order %s: %s", order.get("order_id"), total_price)
            revenue = Decimal("0.00")

        order_date = order_datetime.date().isoformat()
        daily_totals[order_date]["orders"] = int(daily_totals[order_date]["orders"]) + 1
        daily_totals[order_date]["revenue"] = Decimal(daily_totals[order_date]["revenue"]) + revenue

    normalized_orders = [
        {
            "date": order_date,
            "orders": int(values["orders"]),
            "revenue": float(values["revenue"]),
        }
        for order_date, values in sorted(daily_totals.items())
    ]

    return normalized_orders


def load_existing_orders() -> List[Dict[str, object]]:
    if not ORDERS_DAILY_FILE.exists():
        return []

    with ORDERS_DAILY_FILE.open("r", encoding="utf-8") as handle:
        existing_orders = json.load(handle)

    if not isinstance(existing_orders, list):
        raise RuntimeError(f"Processed file is not a list: {ORDERS_DAILY_FILE}")

    return existing_orders


def merge_orders(
    existing_orders: List[Dict[str, object]],
    normalized_orders: List[Dict[str, object]],
) -> List[Dict[str, object]]:
    merged_by_date: Dict[str, Dict[str, object]] = {}

    for row in existing_orders:
        order_date = row.get("date")
        if not order_date:
            continue
        merged_by_date[str(order_date)] = {
            "date": str(order_date),
            "orders": int(row.get("orders", 0)),
            "revenue": float(row.get("revenue", 0.0)),
        }

    for row in normalized_orders:
        order_date = row.get("date")
        if not order_date:
            continue
        merged_by_date[str(order_date)] = {
            "date": str(order_date),
            "orders": int(row.get("orders", 0)),
            "revenue": float(row.get("revenue", 0.0)),
        }

    return [merged_by_date[order_date] for order_date in sorted(merged_by_date.keys())]


def write_processed_orders(normalized_orders: List[Dict[str, object]]) -> Path:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    existing_orders = load_existing_orders()
    merged_orders = merge_orders(existing_orders, normalized_orders)

    with ORDERS_DAILY_FILE.open("w", encoding="utf-8") as handle:
        json.dump(merged_orders, handle, indent=2)

    logging.info("Wrote processed daily orders to %s", ORDERS_DAILY_FILE)
    return ORDERS_DAILY_FILE


def main() -> int:
    setup_logging()

    try:
        store_url = get_required_env("SHOPIFY_STORE_URL")
        api_key = get_required_env("SHOPIFY_API_KEY")
        created_at_min = (datetime.now(timezone.utc) - timedelta(hours=48)).replace(microsecond=0).isoformat()

        logging.info("Starting Shopify ingest for store %s from %s", store_url, created_at_min)

        session = build_session(api_key)
        fetched_orders = fetch_orders(session, store_url, created_at_min)
        simplified_orders = simplify_orders(fetched_orders)
        normalized_orders = normalize_orders(simplified_orders)

        write_raw_orders(simplified_orders)
        write_processed_orders(normalized_orders)

        logging.info("Shopify ingest complete. Processed %s unique orders.", len(simplified_orders))
        return 0
    except Exception as exc:
        logging.exception("Shopify ingest failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
