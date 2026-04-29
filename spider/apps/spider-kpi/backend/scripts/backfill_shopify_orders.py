"""One-shot Shopify order backfill — pull line_items / fulfillments
back through the ShipStation window (≈ 2 years) so the cost-by-SKU
service has SKU truth to JOIN against historical shipments.

Why this script (not the existing /api/admin/backfill route): the
HTTP route ties up a worker for the entire backfill duration and
would hit the gateway / load balancer idle timeout long before
Shopify finishes paginating ~17k orders. Running it as a long-lived
process on the droplet avoids that.

USAGE (on the droplet):

    # Default — backfill to whatever settings.backfill_days is
    # currently set to (824 days at time of writing).
    cd /opt/spiderclawkpi/spider/apps/spider-kpi/backend
    python -m scripts.backfill_shopify_orders

    # Custom window in days:
    python -m scripts.backfill_shopify_orders --days 760

What it does:
  * Calls sync_shopify_orders(db, hours=24*days) once.
  * That function paginates Shopify via cursor links and upserts
    poll.order_snapshot events idempotently — so re-runs are safe.
  * Logs per-stage stats (records_fetched / inserted / updated /
    duplicates_skipped) and total elapsed.

Side effects: writes ShopifyOrderEvent rows. Does NOT modify
ShipStation, ClickUp, or any other connector. Does NOT publish
anything externally.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from app.db.session import SessionLocal
from app.ingestion.connectors.shopify import sync_shopify_orders


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days",
        type=int,
        default=824,
        help="Lookback window in days. Default 824 (≈ 2.25 years, matches ShipStation depth).",
    )
    args = parser.parse_args()

    _setup_logging()
    log = logging.getLogger("backfill_shopify")

    hours = max(1, args.days) * 24
    log.info("Starting Shopify backfill: hours=%d (≈ %d days)", hours, args.days)

    started = time.monotonic()
    db = SessionLocal()
    try:
        result = sync_shopify_orders(db, hours=hours)
    finally:
        db.close()
    elapsed = time.monotonic() - started

    log.info("Backfill complete in %.1fs: %s", elapsed, result)
    if not result.get("ok", True):
        log.error("Backfill reported error: %s", result)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
