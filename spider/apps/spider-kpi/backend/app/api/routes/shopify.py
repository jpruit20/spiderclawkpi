"""Shopify-specific public endpoints.

Primary motivation: the Operations page needs **order aging** — how many
currently-unfulfilled orders sit in each age bucket (0-1d, 1-3d, 3-7d,
7d+), plus a daily trend so the team can see whether the backlog is
clearing or piling up.

The CX page consumes a slim version of the same data to correlate
against WISMO ticket trends: if unfulfilled-aged-7d+ spikes, WISMO
tickets tend to follow.

Data flow:
  Shopify API
    └── sync_shopify_orders / sync_unfulfilled_orders  (connector)
        └── ShopifyOrderEvent.raw_payload + normalized_payload
            └── /api/shopify/order-aging  (this file)
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_dashboard_session
from app.models import ShopifyOrderEvent

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/shopify",
    tags=["shopify"],
    dependencies=[Depends(require_dashboard_session)],
)


# ── Aging buckets ────────────────────────────────────────────────────
#
# Bucket edges in DAYS. An order is placed in the first bucket whose
# upper bound is greater than the order's age. The last bucket has no
# upper bound (7+ days). Tuned to surface "getting stale" before it's
# a crisis — Conor wanted visibility at each of these thresholds.

BUCKETS: tuple[tuple[str, float, Optional[float]], ...] = (
    ("0-1d", 0.0, 1.0),
    ("1-3d", 1.0, 3.0),
    ("3-7d", 3.0, 7.0),
    ("7d+",  7.0, None),
)


def _bucket_for_age_days(age_days: float) -> str:
    for label, low, high in BUCKETS:
        if age_days >= low and (high is None or age_days < high):
            return label
    return BUCKETS[-1][0]


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _latest_snapshot_rows(db: Session) -> list[tuple[str, dict, dict]]:
    """Return (order_id, raw_payload, normalized_payload) for the most
    recent `poll.order_snapshot` event per order_id.

    Uses a PostgreSQL DISTINCT ON for efficiency. Orders without a
    snapshot event (edge case) are excluded.
    """
    stmt = (
        select(
            ShopifyOrderEvent.order_id,
            ShopifyOrderEvent.raw_payload,
            ShopifyOrderEvent.normalized_payload,
        )
        .where(ShopifyOrderEvent.event_type == "poll.order_snapshot")
        .where(ShopifyOrderEvent.order_id.is_not(None))
        .order_by(
            ShopifyOrderEvent.order_id,
            desc(ShopifyOrderEvent.event_timestamp),
        )
        .distinct(ShopifyOrderEvent.order_id)
    )
    return [(r[0], r[1] or {}, r[2] or {}) for r in db.execute(stmt).all()]


@router.get("/order-aging")
def order_aging(
    trend_days: int = 14,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Order-aging report.

    Returns:
      current:
        generated_at: ISO timestamp
        total_unfulfilled: int
        buckets: [{label, low_days, high_days, count, oldest_order_days, total_value_usd}]
        oldest_orders: list of the 5 oldest unfulfilled orders (preview)
      trend:
        days: [N most recent business days]
        series: [{label, counts: [n per day, same length as `days`]}]
      meta:
        method: 'snapshot_reconstruction'
        notes: brief human explanation
    """
    now = datetime.now(timezone.utc)
    rows = _latest_snapshot_rows(db)

    # ── CURRENT aging state ──
    #
    # Filter carefully: old ShopifyOrderEvent snapshots (taken before we
    # started capturing fulfillment_status + fulfillments) can LOOK
    # unfulfilled because fulfillment_status defaults to None. Skip any
    # snapshot that doesn't explicitly carry the field — we'd rather
    # under-count than show 1,500 phantom unfulfilled orders.
    def _has_fulfillment_data(raw: dict, normalized: dict) -> bool:
        return ("fulfillment_status" in raw) or ("fulfillment_status" in normalized)

    open_orders: list[dict[str, Any]] = []
    stale_snapshot_skipped = 0
    for order_id, raw, normalized in rows:
        if not order_id:
            continue
        # Cancelled orders don't count as "waiting on fulfillment."
        cancelled_at = _parse_iso(raw.get("cancelled_at") or normalized.get("cancelled_at"))
        if cancelled_at is not None:
            continue
        if not _has_fulfillment_data(raw, normalized):
            stale_snapshot_skipped += 1
            continue
        # fulfillment_status is either 'fulfilled', 'partial', 'restocked',
        # null (unfulfilled), or 'unfulfilled'. Anything not 'fulfilled'
        # means work remains — but exclude 'restocked' which means
        # returned/restocked (not an open fulfillment).
        fs_raw = raw.get("fulfillment_status")
        if fs_raw is None:
            fs_raw = normalized.get("fulfillment_status")
        fs = (fs_raw or "").lower()
        if fs in ("fulfilled", "restocked"):
            continue
        created_at = _parse_iso(raw.get("created_at") or normalized.get("created_at"))
        if created_at is None:
            continue
        age_days = (now - created_at).total_seconds() / 86400.0
        # Exclude future-dated oddities
        if age_days < 0:
            continue
        first_fulfilled_at = _parse_iso(normalized.get("first_fulfilled_at"))
        total_value = 0.0
        try:
            total_value = float(raw.get("total_price") or normalized.get("total_price") or 0.0)
        except (TypeError, ValueError):
            pass
        open_orders.append({
            "order_id": order_id,
            "created_at": created_at,
            "age_days": age_days,
            "bucket": _bucket_for_age_days(age_days),
            "fulfillment_status": fs or "unfulfilled",
            "first_fulfilled_at": first_fulfilled_at,
            "total_value": total_value,
            "tags": normalized.get("tags") or [],
        })

    # Aggregate current buckets
    bucket_stats: dict[str, dict[str, float]] = {
        label: {"count": 0, "oldest_age_days": 0.0, "total_value_usd": 0.0}
        for label, _, _ in BUCKETS
    }
    for o in open_orders:
        b = bucket_stats[o["bucket"]]
        b["count"] += 1
        b["total_value_usd"] += o["total_value"]
        if o["age_days"] > b["oldest_age_days"]:
            b["oldest_age_days"] = o["age_days"]

    current_buckets = [
        {
            "label": label,
            "low_days": low,
            "high_days": high,
            "count": int(bucket_stats[label]["count"]),
            "oldest_order_days": round(bucket_stats[label]["oldest_age_days"], 2),
            "total_value_usd": round(bucket_stats[label]["total_value_usd"], 2),
        }
        for (label, low, high) in BUCKETS
    ]

    # Preview: the 5 oldest unfulfilled orders
    oldest_preview = sorted(open_orders, key=lambda o: o["age_days"], reverse=True)[:5]
    oldest_preview_out = [
        {
            "order_id": o["order_id"],
            "age_days": round(o["age_days"], 2),
            "bucket": o["bucket"],
            "fulfillment_status": o["fulfillment_status"],
            "total_value_usd": round(o["total_value"], 2),
            "created_at": o["created_at"].isoformat() if o["created_at"] else None,
            "tags": o["tags"],
        }
        for o in oldest_preview
    ]

    # ── TREND reconstruction ──
    #
    # For each of the last `trend_days` days (ending today), count
    # orders that were AT THE TIME still open (not yet fulfilled, not
    # cancelled) and bucket by age-as-of-that-day. This works because
    # we have `created_at`, `first_fulfilled_at` (from the fulfillments
    # sub-array), and `cancelled_at` on every snapshot. Orders that
    # have *since* been fulfilled are correctly excluded from the past
    # day if their first fulfillment happened before that day.
    trend_days = max(1, min(trend_days, 90))
    series_counts: dict[str, list[int]] = {label: [0] * trend_days for label, _, _ in BUCKETS}
    day_labels: list[str] = []

    # Use all snapshots, not just the open_orders filtered list, because
    # an order that is currently fulfilled might still have been open
    # on a past day.
    for i in range(trend_days):
        # Day anchor: end-of-day UTC, trend_days-1 days ago up to today
        offset = trend_days - 1 - i
        anchor = (now - timedelta(days=offset)).replace(hour=23, minute=59, second=59, microsecond=0)
        day_labels.append(anchor.date().isoformat())

        for _, raw, normalized in rows:
            # Same stale-snapshot filter as current state — can't
            # reconstruct history from a snapshot that lacks the
            # fulfillment fields.
            if not _has_fulfillment_data(raw, normalized):
                continue
            created_at = _parse_iso(raw.get("created_at") or normalized.get("created_at"))
            if created_at is None or created_at > anchor:
                continue
            cancelled_at = _parse_iso(raw.get("cancelled_at") or normalized.get("cancelled_at"))
            if cancelled_at is not None and cancelled_at <= anchor:
                continue
            first_fulfilled_at = _parse_iso(normalized.get("first_fulfilled_at"))
            if first_fulfilled_at is not None and first_fulfilled_at <= anchor:
                continue
            # Was open at this anchor; bucket by age-as-of-anchor.
            age_days = (anchor - created_at).total_seconds() / 86400.0
            if age_days < 0:
                continue
            label = _bucket_for_age_days(age_days)
            series_counts[label][i] += 1

    trend_series = [
        {"label": label, "counts": series_counts[label]}
        for label, _, _ in BUCKETS
    ]

    # Freshness: newest snapshot we saw
    newest_ts = db.execute(
        select(ShopifyOrderEvent.event_timestamp)
        .where(ShopifyOrderEvent.event_type == "poll.order_snapshot")
        .order_by(desc(ShopifyOrderEvent.event_timestamp))
        .limit(1)
    ).scalar()

    total_unfulfilled = sum(b["count"] for b in current_buckets)
    total_value = sum(b["total_value_usd"] for b in current_buckets)

    return {
        "current": {
            "generated_at": now.isoformat(),
            "newest_snapshot_at": newest_ts.isoformat() if newest_ts else None,
            "total_unfulfilled": int(total_unfulfilled),
            "total_unfulfilled_value_usd": round(total_value, 2),
            "buckets": current_buckets,
            "oldest_orders": oldest_preview_out,
        },
        "trend": {
            "days": day_labels,
            "series": trend_series,
        },
        "meta": {
            "method": "snapshot_reconstruction",
            "snapshot_rows_scanned": len(rows),
            "stale_snapshot_skipped": stale_snapshot_skipped,
            "notes": (
                "Trend reconstructed from per-order snapshot state "
                "(created_at, first_fulfilled_at, cancelled_at). Counts are "
                "'orders still open at end-of-day, bucketed by age as of "
                "that day'. Snapshots captured before fulfillment_status was "
                "added to the sync are excluded to prevent phantom "
                "unfulfilled counts — click 'Refresh from Shopify' to "
                "backfill current state."
            ),
        },
    }


@router.post("/sync-unfulfilled")
def trigger_unfulfilled_sync(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Manually trigger a refresh of every currently-unfulfilled order.

    Use when the order-aging endpoint looks incomplete or stale (e.g.
    after first deploy of this feature, to backfill orders older than
    the 48h regular poll window). The scheduler also calls this on a
    longer cadence — see the ops runbook.
    """
    from app.ingestion.connectors.shopify import sync_unfulfilled_orders
    return sync_unfulfilled_orders(db)
