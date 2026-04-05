#!/usr/bin/env python3
from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path
import sys

from sqlalchemy import create_engine, text


def fetch_rows(conn, table: str, start: str, end: str):
    rows = conn.execute(
        text(
            f"""
            select business_date, orders, revenue
            from {table}
            where business_date between :start and :end
            order by business_date
            """
        ),
        {"start": start, "end": end},
    ).mappings().all()
    return rows


def summarize(rows):
    revenue = sum(Decimal(str(r["revenue"] or 0)) for r in rows)
    orders = sum(int(r["orders"] or 0) for r in rows)
    return revenue, orders


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Shopify/KPI daily rows for a date window")
    parser.add_argument("--db-url", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    args = parser.parse_args()

    engine = create_engine(args.db_url, future=True)
    with engine.connect() as conn:
        shop_rows = fetch_rows(conn, "shopify_orders_daily", args.start, args.end)
        kpi_rows = fetch_rows(conn, "kpi_daily", args.start, args.end)

    shop_rev, shop_orders = summarize(shop_rows)
    kpi_rev, kpi_orders = summarize(kpi_rows)

    print("SHOPIFY_ROWS")
    for row in shop_rows:
        print(f"{row['business_date']}|{row['orders']}|{row['revenue']}")
    print(f"SHOPIFY_TOTAL|{shop_orders}|{shop_rev}")
    print()
    print("KPI_ROWS")
    for row in kpi_rows:
        print(f"{row['business_date']}|{row['orders']}|{row['revenue']}")
    print(f"KPI_TOTAL|{kpi_orders}|{kpi_rev}")

    if (shop_orders, shop_rev) != (kpi_orders, kpi_rev):
        print("MISMATCH|shopify_vs_kpi")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
