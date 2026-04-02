#!/usr/bin/env python3
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional

import requests
from requests.utils import parse_header_links


BASE_DIR = Path("/home/jpruit20/.openclaw/workspace/spider-kpi")
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
LOG_DIR = BASE_DIR / "logs"
RAW_PREFIX = "orders_"
LOG_FILE = LOG_DIR / "ingest.log"
PROCESSED_FILE = PROCESSED_DIR / "orders_daily.json"
API_VERSION = "2024-10"
MAX_RETRIES = 5
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


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def create_session(api_key: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "X-Shopify-Access-Token": api_key,
            "Accept": "application/json",
        }
    )
    return session


def retry_delay(response: Optional[requests.Response], attempt: int) -> int:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(1, int(float(retry_after)))
            except ValueError:
                logging.warning("Invalid Retry-After value: %s", retry_after)
    return max(1, attempt * 2)


def request_json(
    session: requests.Session,
    url: str,
    params: Optional[Dict[str, str]] = None,
) -> requests.Response:
    last_error: Optional[Exception] = None

    for attempt in range(1, MAX_RETRIES + 1):
        response: Optional[requests.Response] = None
        try:
            response = session.get(url, params=params, timeout=TIMEOUT_SECONDS)
            if response.status_code in {429, 500, 502, 503, 504}:
                delay = retry_delay(response, attempt)
                logging.warning(
                    "Shopify returned %s. Retrying in %ss.",
                    response.status_code,
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
            delay = retry_delay(response, attempt)
            logging.warning("Request failed: %s. Retrying in %ss.", exc, delay)
            time.sleep(delay)

    raise RuntimeError(f"Request failed after {MAX_RETRIES} attempts: {last_error}")


def next_link(link_header: Optional[str]) -> Optional[str]:
    if not link_header:
        return None

    normalized = link_header.replace(">,<", ",<")
    links = parse_header_links(normalized)
    for link in links:
        if link.get("rel") == "next":
            return link.get("url")
    return None


def parse_created_at(value: str) -> datetime:
    clean_value = value.strip()
    if clean_value.endswith("Z"):
        clean_value = clean_value[:-1] + "+00:00"
    return datetime.fromisoformat(clean_value)


def fetch_orders(
    session: requests.Session,
    store_url: str,
    created_at_min: str,
) -> List[Dict[str, object]]:
    url = f"https://{store_url}/admin/api/{API_VERSION}/orders.json"
    params = {
        "status": "any",
        "limit": "250",
        "order": "created_at asc",
        "created_at_min": created_at_min,
        "fields": "id,created_at,total_price,customer.id",
    }

    orders: List[Dict[str, object]] = []
    seen_ids = set()
    next_url: Optional[str] = url
    next_params: Optional[Dict[str, str]] = params

    while next_url:
        response = request_json(session, next_url, next_params)
        payload = response.json()
        batch = payload.get("orders", [])

        for order in batch:
            order_id = order.get("id")
            if order_id in seen_ids:
                continue
            seen_ids.add(order_id)
            orders.append(order)

        logging.info("Fetched %s orders, kept %s unique.", len(batch), len(orders))
        next_url = next_link(response.headers.get("Link"))
        next_params = None

    return orders


def simplify_orders(orders: List[Dict[str, object]]) -> List[Dict[str, object]]:
    simplified_orders: List[Dict[str, object]] = []

    for order in orders:
        customer = order.get("customer")
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


def save_raw_orders(simplified_orders: List[Dict[str, object]]) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RAW_DIR / f"{RAW_PREFIX}{stamp}.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(simplified_orders, handle, indent=2)
    return path


def add_revenue(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def normalize_orders(
    simplified_orders: List[Dict[str, object]],
) -> List[Dict[str, object]]:
    grouped: Dict[str, Dict[str, object]] = {}

    for order in simplified_orders:
        created_at = order.get("created_at")
        if not created_at:
            continue

        try:
            order_date = parse_created_at(str(created_at)).date().isoformat()
        except ValueError:
            continue

        if order_date not in grouped:
            grouped[order_date] = {
                "date": order_date,
                "orders": 0,
                "revenue": Decimal("0.00"),
            }

        grouped[order_date]["orders"] = int(grouped[order_date]["orders"]) + 1
        grouped[order_date]["revenue"] = (
            Decimal(grouped[order_date]["revenue"])
            + add_revenue(order.get("total_price"))
        )

    normalized_orders: List[Dict[str, object]] = []
    for order_date in sorted(grouped.keys()):
        row = grouped[order_date]
        normalized_orders.append(
            {
                "date": row["date"],
                "orders": int(row["orders"]),
                "revenue": float(row["revenue"]),
            }
        )

    return normalized_orders


def load_existing_orders() -> List[Dict[str, object]]:
    if not PROCESSED_FILE.exists():
        return []

    with PROCESSED_FILE.open("r", encoding="utf-8") as handle:
        existing_orders = json.load(handle)

    if not isinstance(existing_orders, list):
        raise RuntimeError(f"Invalid processed file: {PROCESSED_FILE}")

    return existing_orders


def merge_orders(
    existing_orders: List[Dict[str, object]],
    normalized_orders: List[Dict[str, object]],
) -> List[Dict[str, object]]:
    merged: Dict[str, Dict[str, object]] = {}

    for row in existing_orders:
        order_date = row.get("date")
        if not order_date:
            continue
        merged[str(order_date)] = {
            "date": str(order_date),
            "orders": int(row.get("orders", 0)),
            "revenue": float(row.get("revenue", 0.0)),
        }

    for row in normalized_orders:
        order_date = row.get("date")
        if not order_date:
            continue
        merged[str(order_date)] = {
            "date": str(order_date),
            "orders": int(row.get("orders", 0)),
            "revenue": float(row.get("revenue", 0.0)),
        }

    return [merged[key] for key in sorted(merged.keys())]


def save_processed_orders(normalized_orders: List[Dict[str, object]]) -> Path:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    existing_orders = load_existing_orders()
    merged_orders = merge_orders(existing_orders, normalized_orders)
    with PROCESSED_FILE.open("w", encoding="utf-8") as handle:
        json.dump(merged_orders, handle, indent=2)
    return PROCESSED_FILE


def main() -> int:
    setup_logging()

    try:
        store_url = require_env("SHOPIFY_STORE_URL")
        api_key = require_env("SHOPIFY_API_KEY")
        created_at_min = (
            datetime.now(timezone.utc) - timedelta(hours=48)
        ).replace(microsecond=0).isoformat()

        session = create_session(api_key)
        orders = fetch_orders(session, store_url, created_at_min)
        simplified_orders = simplify_orders(orders)
        normalized_orders = normalize_orders(simplified_orders)

        raw_path = save_raw_orders(simplified_orders)
        processed_path = save_processed_orders(normalized_orders)

        logging.info("Saved raw orders to %s", raw_path)
        logging.info("Saved processed orders to %s", processed_path)
        logging.info("Processed %s unique orders.", len(simplified_orders))
        return 0
    except Exception as exc:
        logging.exception("Shopify ingest failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
