"""Product COGS — single source of truth for gross-profit math.

Reads canonical per-unit COGS from
``sharepoint_product_intelligence.cogs_summary.canonical_total_usd``
and exposes:

- ``get_canonical_cogs()`` — dict of {product: {cogs_usd, confidence,
  source_doc_id, source_doc_name, synthesized_at}}
- ``compute_gross_profit(start, end)`` — revenue, per-product units
  sold, applied COGS, gross profit, gross margin %, with
  data_quality_flags when COGS is missing or confidence is low

Used by:
- /api/financials/cogs-table — per-product COGS for the financial review
- /api/financials/gross-profit — windowed P&L line so executive,
  commercial, marketing, and command-center pages all read the same
  number
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import (
    SharepointDocument,
    SharepointProductIntelligence,
    ShopifyOrderEvent,
)


# Spider's canonical product set
PRODUCTS = ("Huntsman", "Giant Huntsman", "Venom", "Webcraft", "Giant Webcraft")


def _norm_title(title: str) -> str:
    """Normalize a Shopify line_item title for matching: lowercase,
    strip ™ ® ©, collapse whitespace."""
    t = (title or "").lower().replace("™", "").replace("®", "").replace("©", "")
    return " ".join(t.split())


# CANONICAL grill/controller titles — only the core SKU we apply COGS to.
# Accessories (covers, side shelves, rotisseries, pizza ovens, lift kits,
# seasoning kits, replacement parts, probes, batteries, cables, gaskets,
# hinges, conversion clips, NextLevel cooking systems) explicitly DO NOT
# match here. They sell with their own retail prices and we don't have a
# per-unit COGS for them, so counting them toward grill margins double-
# counted accessory revenue at grill-COGS — produced false negative
# margins like Huntsman -11.79%. Spot-checked 2026-04-26.
_CANONICAL_TITLES: dict[str, str] = {
    # Huntsman line
    "the huntsman": "Huntsman",
    "giant huntsman": "Giant Huntsman",
    # Venom controller (the "Venom" product is the controller, not a grill)
    "venom digital temperature controller": "Venom",
    # Webcraft kit (two casings live in the catalog)
    'the webcraft for 22" weber kettles': "Webcraft",
}


def _classify_line_item_title(title: str) -> Optional[str]:
    """Exact-canonical matcher. Returns the product family ONLY for
    the core SKU titles we have COGS for; everything else (accessories,
    parts, bundles, replacements) returns None and is counted as
    'unclassified revenue' in the rollup so the math stays honest."""
    nt = _norm_title(title)
    if not nt:
        return None
    return _CANONICAL_TITLES.get(nt)


def get_canonical_cogs(db: Session) -> dict[str, dict[str, Any]]:
    """Pull canonical per-unit COGS for every product from the
    SharePoint synthesis. Products without a synthesis row are absent
    from the returned dict (caller can decide how to handle missing)."""
    rows = db.execute(select(SharepointProductIntelligence)).scalars().all()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        cogs = (r.cogs_summary or {})
        canonical = cogs.get("canonical_total_usd")
        if canonical is None:
            continue
        doc_id = cogs.get("canonical_document_id")
        doc_name = None
        web_url = None
        if doc_id:
            doc = db.get(SharepointDocument, int(doc_id))
            if doc:
                doc_name = doc.name
                web_url = doc.web_url
        out[r.spider_product] = {
            "cogs_usd": float(canonical),
            "confidence": cogs.get("confidence") or "low",
            "source_doc_id": int(doc_id) if doc_id else None,
            "source_doc_name": doc_name,
            "source_web_url": web_url,
            "notes": cogs.get("notes"),
            "synthesized_at": r.synthesized_at.isoformat() if r.synthesized_at else None,
        }
    return out


def units_by_product_in_window(
    db: Session,
    *,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> dict[str, dict[str, Any]]:
    """Sum NET line-item revenue by product family within [start, end).

    Net revenue means: per-line ``price * quantity`` MINUS line-level
    discount, MINUS the line's pro-rata share of order-level discount
    (when ``line.total_discount`` doesn't already absorb it).

    Excluded from the rollup:
    - Cancelled orders (``cancelled_at`` set)
    - Fully refunded orders (``financial_status='refunded'``)
    Partially refunded orders stay in (Shopify's ``total_price`` is
    pre-refund, so we subtract the refund amount in
    ``compute_gross_profit`` per-order).

    Other correctness:
    - Polls the same order multiple times — dedupe by order_id taking
      the LATEST snapshot (so we get the freshest line_items).
    - Window filter uses **business_date** (the order's actual
      creation date from Shopify), NOT event_timestamp. event_timestamp
      reflects the latest *poll/update* time — when an old order is
      re-polled today (refund, fulfillment update), event_timestamp
      jumps to today and the order would falsely count in today's
      revenue. business_date ties revenue to when the order was placed.
    """
    where_parts = [
        "event_type = 'poll.order_snapshot'",
        "order_id IS NOT NULL",
    ]
    params: dict[str, Any] = {}
    if start is not None:
        where_parts.append("business_date >= :start_d")
        params["start_d"] = start
    if end is not None:
        where_parts.append("business_date < :end_d")
        params["end_d"] = end
    where_sql = " AND ".join(where_parts)

    # Pull (order, line) pairs for non-cancelled, non-fully-refunded orders.
    # Carry order-level fields so we can pro-rate discounts and subtract refunds.
    rows = db.execute(text(f"""
        WITH latest AS (
            SELECT DISTINCT ON (order_id)
                order_id,
                raw_payload,
                event_timestamp
            FROM shopify_order_events
            WHERE {where_sql}
            ORDER BY order_id, event_timestamp DESC NULLS LAST, id DESC
        ),
        eligible AS (
            SELECT * FROM latest
            WHERE COALESCE(raw_payload->>'cancelled_at', '') = ''
              AND COALESCE(raw_payload->>'financial_status', '') <> 'refunded'
              AND jsonb_typeof(raw_payload->'line_items') = 'array'
        )
        SELECT
            order_id,
            COALESCE((raw_payload->>'total_discounts')::numeric, 0) AS order_disc,
            COALESCE((raw_payload->>'financial_status')::text, '') AS fin_status,
            line->>'title' AS title,
            COALESCE((line->>'quantity')::int, 0) AS qty,
            COALESCE((line->>'price')::numeric, 0) AS unit_price,
            COALESCE((line->>'total_discount')::numeric, 0) AS line_disc
        FROM eligible, jsonb_array_elements(raw_payload->'line_items') AS line
    """), params).all()

    # Group by order to allocate any leftover order-level discount across lines.
    by_order: dict[str, list[dict[str, Any]]] = {}
    order_discount: dict[str, float] = {}
    for r in rows:
        oid = r.order_id
        by_order.setdefault(oid, []).append({
            "title": r.title or "",
            "qty": int(r.qty),
            "unit_price": float(r.unit_price),
            "line_disc": float(r.line_disc),
        })
        order_discount[oid] = float(r.order_disc)

    by_product: dict[str, dict[str, Any]] = {p: {"units": 0, "revenue": 0.0} for p in PRODUCTS}
    unclassified_units = 0
    unclassified_revenue = 0.0
    total_discount_applied = 0.0

    for oid, lines in by_order.items():
        gross_lines = [l["unit_price"] * l["qty"] for l in lines]
        order_gross = sum(gross_lines) or 1.0  # avoid div0
        line_disc_sum = sum(l["line_disc"] for l in lines)
        # Any order-level discount NOT already represented in line.total_discount
        # gets allocated proportionally across line gross.
        order_disc_total = order_discount.get(oid, 0.0)
        unallocated = max(0.0, order_disc_total - line_disc_sum)
        for i, l in enumerate(lines):
            gross = gross_lines[i]
            allocated_extra = (gross / order_gross) * unallocated if order_gross else 0
            net_line = max(0.0, gross - l["line_disc"] - allocated_extra)
            total_discount_applied += (l["line_disc"] + allocated_extra)
            fam = _classify_line_item_title(l["title"])
            if fam is None:
                unclassified_units += l["qty"]
                unclassified_revenue += net_line
            else:
                by_product[fam]["units"] += l["qty"]
                by_product[fam]["revenue"] += net_line

    # Coverage / counts
    counts = db.execute(text(f"""
        WITH latest AS (
            SELECT DISTINCT ON (order_id) order_id, raw_payload
            FROM shopify_order_events
            WHERE {where_sql}
            ORDER BY order_id, event_timestamp DESC NULLS LAST, id DESC
        )
        SELECT
            count(*) AS total_orders,
            count(*) FILTER (WHERE jsonb_typeof(raw_payload->'line_items') = 'array') AS orders_with_lines,
            count(*) FILTER (WHERE COALESCE(raw_payload->>'cancelled_at','') <> '') AS cancelled,
            count(*) FILTER (WHERE raw_payload->>'financial_status' = 'refunded') AS refunded,
            count(*) FILTER (WHERE raw_payload->>'financial_status' = 'partially_refunded') AS partial_refund,
            COALESCE(SUM((raw_payload->>'total_price')::numeric) FILTER (WHERE raw_payload->>'financial_status' = 'refunded'), 0) AS refunded_amt
        FROM latest
    """), params).first()

    return {
        "by_product": by_product,
        "unclassified_units": unclassified_units,
        "unclassified_revenue": unclassified_revenue,
        "discounts_applied_usd": total_discount_applied,
        "excluded": {
            "cancelled_orders": int(counts.cancelled or 0),
            "refunded_orders": int(counts.refunded or 0),
            "refunded_revenue_usd": float(counts.refunded_amt or 0),
            "partially_refunded_orders": int(counts.partial_refund or 0),
        },
        "coverage_orders_with_line_items": int(counts.orders_with_lines or 0),
        "coverage_orders_total": int(counts.total_orders or 0),
    }


# Estimated cost-of-goods ratio applied to accessory line items (covers,
# side shelves, rotisseries, lift kits, replacement parts, etc.) where
# we don't have an extracted CBOM. 0.50 is the operator's stated prior:
# "COGS is roughly 40-50% of retail" — staying at the high end keeps the
# blended margin honest rather than rosy. Surface in the API response so
# the dashboard footnotes "accessories estimated at X% COGS" and Joseph
# can override if needed.
DEFAULT_ACCESSORY_COGS_RATIO = 0.50


def shipping_cost_in_window(
    db: Session,
    *,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> dict[str, Any]:
    """Sum carrier shipping cost from ShipStation shipments within
    [start, end). Voided shipments are excluded. Filtered to the
    Spider store allowlist (defense-in-depth — connector also filters
    server-side, but we re-filter here in case rows from another
    company's stores ever leak in).

    Returns:
      total_cost: shipment_cost + insurance_cost summed
      shipment_count, voided_count
      by_store: per-store breakdown
      by_order: {ss_order_number: cost} for per-order attribution
    """
    where = [
        "voided = FALSE",
        "ss_store_id = ANY(:allowlist)",
    ]
    params: dict[str, Any] = {
        "allowlist": list(get_settings().shipstation_spider_store_ids or []),
    }
    if start is not None:
        where.append("ship_date >= :start_d")
        params["start_d"] = start
    if end is not None:
        where.append("ship_date < :end_d")
        params["end_d"] = end

    where_sql = " AND ".join(where)
    rows = db.execute(text(f"""
        SELECT
            ss_store_id,
            ss_order_number,
            COALESCE(shipment_cost, 0) + COALESCE(insurance_cost, 0) AS total_cost
        FROM shipstation_shipments
        WHERE {where_sql}
    """), params).all()

    total = 0.0
    by_store: dict[int, float] = {}
    by_order: dict[str, float] = {}
    for r in rows:
        c = float(r.total_cost or 0)
        total += c
        by_store[r.ss_store_id] = by_store.get(r.ss_store_id, 0.0) + c
        if r.ss_order_number:
            by_order[r.ss_order_number] = by_order.get(r.ss_order_number, 0.0) + c

    voided = db.execute(text(f"""
        SELECT count(*) FROM shipstation_shipments
        WHERE ss_store_id = ANY(:allowlist) AND voided = TRUE
        {("AND ship_date >= :start_d" if start else "")}
        {("AND ship_date < :end_d" if end else "")}
    """), params).scalar() or 0

    return {
        "total_cost_usd": round(total, 2),
        "shipment_count": len(rows),
        "voided_count": int(voided),
        "by_store": {int(k): round(v, 2) for k, v in by_store.items()},
        "by_order": by_order,
    }


def get_settings():
    """Lazy import — avoids circular dep at module load time."""
    from app.core.config import get_settings as _gs
    return _gs()


def compute_gross_profit(
    db: Session,
    *,
    days: Optional[int] = None,
    start: Optional[date] = None,
    end: Optional[date] = None,
    accessory_cogs_ratio: float = DEFAULT_ACCESSORY_COGS_RATIO,
) -> dict[str, Any]:
    """Cross-platform gross-profit calculator. Joins per-product unit
    counts with canonical COGS to produce revenue, COGS, gross profit,
    and gross margin. Same numbers regardless of which dashboard page
    calls it.

    Window precedence: explicit (start, end) > days-back from today.
    Default (no args) = lifetime.

    Accessory revenue (line items that aren't a core grill/controller)
    has no extracted CBOM, so we apply ``accessory_cogs_ratio`` (default
    50%) as an estimate. The blended margin reflects that estimate;
    classified per-product margins are exact.
    """
    if start is None and end is None and days is not None:
        end = date.today()
        start = end - timedelta(days=days)

    # Whatever window the caller asks for, we MUST measure revenue +
    # COGS + shipping over the same calendar span — otherwise totals
    # don't reconcile. Shopify line_items capture only started landing
    # in late April 2026, so any window stretching earlier than that
    # has zero revenue-side coverage but full shipping-cost coverage,
    # which produces nonsense (GP > rev or large negative margins).
    # Clamp start to the earliest order with line_items so every window
    # is apples-to-apples. Surface the effective window in the response
    # so the frontend can label it.
    line_items_floor = db.execute(text("""
        SELECT MIN(business_date)::date
        FROM shopify_order_events
        WHERE event_type='poll.order_snapshot'
          AND jsonb_typeof(raw_payload->'line_items') = 'array'
    """)).scalar()
    requested_start = start
    if line_items_floor is not None:
        if start is None or start < line_items_floor:
            start = line_items_floor
        if end is None:
            end = (date.today() + timedelta(days=1))
    window_clamped = (requested_start is not None and requested_start != start)

    cogs_table = get_canonical_cogs(db)
    units_data = units_by_product_in_window(db, start=start, end=end)
    rows_by_product = units_data["by_product"]
    shipping_data = shipping_cost_in_window(db, start=start, end=end)

    # Ad spend in the same window from kpi_daily — used to compute
    # contribution margin (revenue - all_cogs - ad_spend) so marketing
    # surfaces "what's actually left after we acquired customers."
    ad_spend_total = 0.0
    refunds_total = 0.0
    if start and end:
        row = db.execute(text("""
            SELECT
                COALESCE(SUM(ad_spend), 0)::numeric AS ad_spend,
                COALESCE(SUM(refunds), 0)::numeric AS refunds
            FROM kpi_daily
            WHERE business_date >= :start AND business_date < :end
        """), {"start": start, "end": end}).first()
        if row:
            ad_spend_total = float(row.ad_spend or 0)
            refunds_total = float(row.refunds or 0)

    by_product: list[dict[str, Any]] = []
    total_revenue = 0.0
    total_units = 0
    total_cogs = 0.0
    flags: list[dict[str, Any]] = []

    for product in PRODUCTS:
        u = rows_by_product[product]["units"]
        r = float(rows_by_product[product]["revenue"])
        cogs_row = cogs_table.get(product)
        unit_cogs = cogs_row["cogs_usd"] if cogs_row else None
        applied_cogs = (unit_cogs or 0) * u
        gross_profit = r - applied_cogs
        gross_margin_pct = (gross_profit / r * 100) if r > 0 else None

        if u > 0 and unit_cogs is None:
            flags.append({
                "severity": "warn",
                "product": product,
                "issue": f"{product} sold {u} units in window but no canonical COGS available — gross profit understated.",
            })
        elif unit_cogs is not None and cogs_row and cogs_row.get("confidence") == "low":
            flags.append({
                "severity": "info",
                "product": product,
                "issue": f"{product} canonical COGS is low-confidence (${unit_cogs:.2f}) — gross profit estimate is rough.",
            })

        total_revenue += r
        total_units += u
        total_cogs += applied_cogs

        by_product.append({
            "product": product,
            "units_sold": u,
            "revenue_usd": round(r, 2),
            "unit_cogs_usd": round(unit_cogs, 2) if unit_cogs is not None else None,
            "applied_cogs_usd": round(applied_cogs, 2),
            "gross_profit_usd": round(gross_profit, 2),
            "gross_margin_pct": round(gross_margin_pct, 2) if gross_margin_pct is not None else None,
            "cogs_confidence": cogs_row.get("confidence") if cogs_row else None,
            "cogs_source_doc_id": cogs_row.get("source_doc_id") if cogs_row else None,
            "cogs_source_doc_name": cogs_row.get("source_doc_name") if cogs_row else None,
            "cogs_source_web_url": cogs_row.get("source_web_url") if cogs_row else None,
        })

    # Accessory line items have no extracted CBOM. Apply the operator's
    # stated COGS prior (default 50% of retail) as an estimate so the
    # blended margin reflects real economics rather than treating
    # accessories as 100% margin.
    unclassified_rev = float(units_data["unclassified_revenue"])
    accessory_cogs = unclassified_rev * accessory_cogs_ratio
    total_revenue_with_unclassified = total_revenue + unclassified_rev
    # Shipping cost (ShipStation) gets folded into applied COGS.
    # Allocate per-product proportionally to product revenue so each
    # product's margin reflects its fair share of carrier cost.
    shipping_total = float(shipping_data.get("total_cost_usd", 0.0))
    shipping_count = int(shipping_data.get("shipment_count", 0))
    if shipping_total > 0 and total_revenue_with_unclassified > 0:
        # Re-apportion across already-emitted by_product rows so shipping
        # is reflected in per-product gross_profit + margin.
        ship_share_total = 0.0
        for entry in by_product:
            r_share = float(entry["revenue_usd"]) / total_revenue_with_unclassified
            ship_share = round(shipping_total * r_share, 2)
            entry["applied_shipping_usd"] = ship_share
            entry["applied_cogs_usd"] = round(float(entry["applied_cogs_usd"]) + ship_share, 2)
            entry["gross_profit_usd"] = round(float(entry["revenue_usd"]) - float(entry["applied_cogs_usd"]), 2)
            r_val = float(entry["revenue_usd"])
            entry["gross_margin_pct"] = round((entry["gross_profit_usd"] / r_val * 100), 2) if r_val > 0 else None
            ship_share_total += ship_share
    else:
        for entry in by_product:
            entry["applied_shipping_usd"] = 0.0

    total_cogs_with_estimate = total_cogs + accessory_cogs + shipping_total
    overall_gross_profit = total_revenue_with_unclassified - total_cogs_with_estimate
    overall_margin = (overall_gross_profit / total_revenue_with_unclassified * 100) if total_revenue_with_unclassified > 0 else None

    if unclassified_rev > 0:
        flags.append({
            "severity": "info",
            "product": "accessories",
            "issue": (
                f"Accessory revenue (${unclassified_rev:,.0f}) has no extracted CBOM. "
                f"Applied estimated COGS at {int(accessory_cogs_ratio * 100)}% of retail (${accessory_cogs:,.0f}). "
                f"Replace with extracted accessory BOMs for exact margins."
            ),
        })
    if shipping_total > 0:
        flags.append({
            "severity": "info",
            "product": "shipping",
            "issue": (
                f"Carrier shipping cost (ShipStation, {shipping_count} shipments): ${shipping_total:,.2f} "
                f"folded into COGS. Allocated to products proportionally to revenue."
            ),
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
            "days": days,
            "requested_start": requested_start.isoformat() if requested_start else None,
            "clamped": window_clamped,
            "clamp_reason": (
                f"Window clamped to line_items coverage start ({start.isoformat() if start else 'unknown'}). "
                "Shopify line_items capture only began on this date — revenue prior to it cannot be reconciled "
                "to COGS/shipping at the line-item level. Pass a later start to see a sub-window."
            ) if window_clamped else None,
        },
        "totals": {
            "revenue_usd": round(total_revenue_with_unclassified, 2),
            "revenue_classified_usd": round(total_revenue, 2),
            "revenue_unclassified_usd": round(unclassified_rev, 2),
            "units_sold": total_units,
            "applied_cogs_usd": round(total_cogs_with_estimate, 2),
            "applied_cogs_classified_usd": round(total_cogs, 2),
            "applied_cogs_accessory_estimate_usd": round(accessory_cogs, 2),
            "applied_shipping_usd": round(shipping_total, 2),
            "gross_profit_usd": round(overall_gross_profit, 2),
            "gross_margin_pct": round(overall_margin, 2) if overall_margin is not None else None,
            "discounts_applied_usd": round(units_data.get("discounts_applied_usd", 0.0), 2),
            # Marketing-side contribution: GP minus ad spend
            "ad_spend_usd": round(ad_spend_total, 2),
            "contribution_margin_usd": round(overall_gross_profit - ad_spend_total, 2),
            "contribution_margin_pct": (
                round((overall_gross_profit - ad_spend_total) / total_revenue_with_unclassified * 100, 2)
                if total_revenue_with_unclassified > 0 else None
            ),
            "refunds_in_kpi_daily_usd": round(refunds_total, 2),
        },
        "by_product": by_product,
        "data_quality_flags": flags,
        "accessory_assumption": {
            "ratio": accessory_cogs_ratio,
            "note": "Accessories use estimated COGS — replace by extracting per-accessory CBOMs.",
        },
        "shipping": {
            "total_cost_usd": round(shipping_total, 2),
            "shipment_count": shipping_count,
            "voided_count": int(shipping_data.get("voided_count", 0)),
            "by_store": shipping_data.get("by_store", {}),
            "note": "From ShipStation Spider stores (Amazon + Shopify + Manual). Allocated to products proportionally to revenue.",
        },
        "excluded": units_data.get("excluded", {}),
        "coverage": {
            "orders_with_line_items": units_data["coverage_orders_with_line_items"],
            "orders_total": units_data["coverage_orders_total"],
            "note": "Shopify line_items capture started 2026-04-21. Orders synced before that don't carry line-item data; gross profit math only applies to the covered subset.",
        },
    }
