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


def _classify_line_item_title(title: str) -> Optional[str]:
    """Map a Shopify line_item title to a Spider product family.
    Conservative matcher — returns None for accessories/attachments."""
    t = (title or "").lower()
    if "giant huntsman" in t:
        return "Giant Huntsman"
    if "giant webcraft" in t or "giant web craft" in t:
        return "Giant Webcraft"
    if "huntsman" in t:
        return "Huntsman"
    if "webcraft" in t or "web craft" in t:
        return "Webcraft"
    if "venom" in t:
        return "Venom"
    return None


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
    """Sum Shopify line-item quantities by product family within
    [start, end). Returns ``{product: {units, revenue}}`` plus
    coverage stats so callers know how much of the order set has
    line_item data."""
    where_parts = ["event_type = 'poll.order_snapshot'", "jsonb_typeof(raw_payload->'line_items') = 'array'"]
    params: dict[str, Any] = {}
    if start is not None:
        where_parts.append("created_at_source >= :start_ts")
        params["start_ts"] = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    if end is not None:
        where_parts.append("created_at_source < :end_ts")
        params["end_ts"] = datetime.combine(end, datetime.min.time(), tzinfo=timezone.utc)
    where_sql = " AND ".join(where_parts)

    rows = db.execute(text(f"""
        WITH li AS (
            SELECT jsonb_array_elements(raw_payload->'line_items') AS line
            FROM shopify_order_events
            WHERE {where_sql}
        )
        SELECT
            lower(coalesce(line->>'title', '')) AS title,
            COALESCE((line->>'quantity')::int, 0) AS qty,
            COALESCE((line->>'price')::numeric, 0) AS unit_price
        FROM li
    """), params).all()

    by_product: dict[str, dict[str, Any]] = {p: {"units": 0, "revenue": 0.0} for p in PRODUCTS}
    unclassified_units = 0
    unclassified_revenue = 0.0
    for title, qty, unit_price in rows:
        fam = _classify_line_item_title(title)
        revenue = float(unit_price) * int(qty)
        if fam is None:
            unclassified_units += int(qty)
            unclassified_revenue += revenue
            continue
        by_product[fam]["units"] += int(qty)
        by_product[fam]["revenue"] += revenue

    # Coverage: how many orders in window vs how many had line_items
    total_q = ["event_type = 'poll.order_snapshot'"]
    if start is not None:
        total_q.append("created_at_source >= :start_ts")
    if end is not None:
        total_q.append("created_at_source < :end_ts")
    cov_total = db.execute(text(f"SELECT count(*) FROM shopify_order_events WHERE {' AND '.join(total_q)}"), params).scalar() or 0
    cov_with = db.execute(text(f"""
        SELECT count(*) FROM shopify_order_events
        WHERE {' AND '.join(total_q)} AND jsonb_typeof(raw_payload->'line_items') = 'array'
    """), params).scalar() or 0

    return {
        "by_product": by_product,
        "unclassified_units": unclassified_units,
        "unclassified_revenue": unclassified_revenue,
        "coverage_orders_with_line_items": int(cov_with),
        "coverage_orders_total": int(cov_total),
    }


def compute_gross_profit(
    db: Session,
    *,
    days: Optional[int] = None,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> dict[str, Any]:
    """Cross-platform gross-profit calculator. Joins per-product unit
    counts with canonical COGS to produce revenue, COGS, gross profit,
    and gross margin. Same numbers regardless of which dashboard page
    calls it.

    Window precedence: explicit (start, end) > days-back from today.
    Default (no args) = lifetime.
    """
    if start is None and end is None and days is not None:
        end = date.today()
        start = end - timedelta(days=days)

    cogs_table = get_canonical_cogs(db)
    units_data = units_by_product_in_window(db, start=start, end=end)
    rows_by_product = units_data["by_product"]

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

    # Unclassified line items (accessories, etc.) count as revenue with 0 COGS
    unclassified_rev = float(units_data["unclassified_revenue"])
    total_revenue_with_unclassified = total_revenue + unclassified_rev
    overall_gross_profit = total_revenue_with_unclassified - total_cogs
    overall_margin = (overall_gross_profit / total_revenue_with_unclassified * 100) if total_revenue_with_unclassified > 0 else None

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
            "days": days,
        },
        "totals": {
            "revenue_usd": round(total_revenue_with_unclassified, 2),
            "revenue_classified_usd": round(total_revenue, 2),
            "revenue_unclassified_usd": round(unclassified_rev, 2),
            "units_sold": total_units,
            "applied_cogs_usd": round(total_cogs, 2),
            "gross_profit_usd": round(overall_gross_profit, 2),
            "gross_margin_pct": round(overall_margin, 2) if overall_margin is not None else None,
        },
        "by_product": by_product,
        "data_quality_flags": flags,
        "coverage": {
            "orders_with_line_items": units_data["coverage_orders_with_line_items"],
            "orders_total": units_data["coverage_orders_total"],
            "note": "Shopify line_items capture started 2026-04-21. Orders synced before that don't carry line-item data; gross profit math only applies to the covered subset.",
        },
    }
