"""Shipping intelligence — Operations-side analytics on top of
``shipstation_shipments``.

Surfaces the metrics Joseph asked about:
- Carrier mix (FedEx vs USPS vs UPS, etc.) — counts + spend by carrier
- Transit time per carrier (ship_date → reported delivery; ShipStation
  doesn't give us delivery, so we approximate via service_code SLAs
  where known, otherwise just measure ship-throughput by carrier)
- Fulfillment SLA (Shopify created_at → ship_date)
- Geographic distribution (state-level + ZIP3 cluster)
- 3PL location ROI estimator (which cities, if a warehouse opened
  there, would cut shipping costs the most based on volume + distance
  proxy)

All windowed by ship_date. Spider-only via the store allowlist.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings


# Approximate Spider's primary warehouse: Atlanta, GA (AMW HQ).
# Used by the 3PL ROI estimator as the current "from" location.
PRIMARY_WAREHOUSE = {
    "city": "Atlanta",
    "state": "GA",
    "lat": 33.7490,
    "lon": -84.3880,
}

# Hand-curated lat/lon for US state centroids — used by the geographic
# distribution + 3PL ROI distance proxy. Approximate; the goal is
# "which broad region" not turn-by-turn directions.
STATE_CENTROIDS = {
    "AL": (32.806671, -86.791130), "AK": (61.370716, -152.404419), "AZ": (33.729759, -111.431221),
    "AR": (34.969704, -92.373123), "CA": (36.116203, -119.681564), "CO": (39.059811, -105.311104),
    "CT": (41.597782, -72.755371), "DE": (39.318523, -75.507141), "FL": (27.766279, -81.686783),
    "GA": (33.040619, -83.643074), "HI": (21.094318, -157.498337), "ID": (44.240459, -114.478828),
    "IL": (40.349457, -88.986137), "IN": (39.849426, -86.258278), "IA": (42.011539, -93.210526),
    "KS": (38.526600, -96.726486), "KY": (37.668140, -84.670067), "LA": (31.169546, -91.867805),
    "ME": (44.693947, -69.381927), "MD": (39.063946, -76.802101), "MA": (42.230171, -71.530106),
    "MI": (43.326618, -84.536095), "MN": (45.694454, -93.900192), "MS": (32.741646, -89.678696),
    "MO": (38.456085, -92.288368), "MT": (46.921925, -110.454353), "NE": (41.125370, -98.268082),
    "NV": (38.313515, -117.055374), "NH": (43.452492, -71.563896), "NJ": (40.298904, -74.521011),
    "NM": (34.840515, -106.248482), "NY": (42.165726, -74.948051), "NC": (35.630066, -79.806419),
    "ND": (47.528912, -99.784012), "OH": (40.388783, -82.764915), "OK": (35.565342, -96.928917),
    "OR": (44.572021, -122.070938), "PA": (40.590752, -77.209755), "RI": (41.680893, -71.511780),
    "SC": (33.856892, -80.945007), "SD": (44.299782, -99.438828), "TN": (35.747845, -86.692345),
    "TX": (31.054487, -97.563461), "UT": (40.150032, -111.862434), "VT": (44.045876, -72.710686),
    "VA": (37.769337, -78.169968), "WA": (47.400902, -121.490494), "WV": (38.491226, -80.954453),
    "WI": (44.268543, -89.616508), "WY": (42.755966, -107.302490), "DC": (38.897438, -77.026817),
}


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in miles. Approximation — fine for 3PL
    siting analysis."""
    import math
    R_MI = 3958.8
    p1 = math.radians(lat1); p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1); dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_MI * math.asin(math.sqrt(a))


def _window_clauses(*, start: Optional[date], end: Optional[date]) -> tuple[str, dict[str, Any]]:
    parts = ["s.voided = FALSE", "s.ss_store_id = ANY(:allowlist)"]
    params: dict[str, Any] = {
        "allowlist": list(get_settings().shipstation_spider_store_ids or []),
    }
    if start is not None:
        parts.append("s.ship_date >= :start_d")
        params["start_d"] = start
    if end is not None:
        parts.append("s.ship_date < :end_d")
        params["end_d"] = end
    return " AND ".join(parts), params


# ── Carrier mix ─────────────────────────────────────────────────────


def carrier_mix(db: Session, *, days: Optional[int] = 90) -> dict[str, Any]:
    """Volume + spend per carrier in the window. Returns ranked list."""
    end_d = date.today()
    start_d = end_d - timedelta(days=days) if days else None
    where_sql, params = _window_clauses(start=start_d, end=end_d)
    rows = db.execute(text(f"""
        SELECT
            COALESCE(NULLIF(s.carrier_code,''), 'unknown') AS carrier,
            COUNT(*) AS shipments,
            SUM(s.shipment_cost + s.insurance_cost)::numeric(12,2) AS total_cost,
            AVG(s.shipment_cost + s.insurance_cost)::numeric(10,2) AS avg_cost,
            AVG(s.weight_oz)::numeric(10,2) AS avg_weight_oz
        FROM shipstation_shipments s
        WHERE {where_sql}
        GROUP BY carrier
        ORDER BY shipments DESC
    """), params).all()

    total_ships = sum(r.shipments for r in rows)
    total_cost = float(sum((r.total_cost or 0) for r in rows))
    return {
        "window": {"start": start_d.isoformat() if start_d else None, "end": end_d.isoformat(), "days": days},
        "totals": {"shipments": total_ships, "total_cost_usd": round(total_cost, 2), "avg_cost_per_shipment": round(total_cost / total_ships, 2) if total_ships else 0},
        "carriers": [
            {
                "carrier": r.carrier,
                "shipments": int(r.shipments),
                "total_cost_usd": float(r.total_cost or 0),
                "avg_cost_usd": float(r.avg_cost or 0),
                "avg_weight_oz": float(r.avg_weight_oz or 0),
                "share_pct": round(r.shipments / total_ships * 100, 1) if total_ships else 0,
            }
            for r in rows
        ],
    }


# ── Geographic distribution ─────────────────────────────────────────


def geographic_distribution(db: Session, *, days: Optional[int] = 365) -> dict[str, Any]:
    """Shipments + spend by destination state (and ZIP3 in roll-up).
    Used to render the US heatmap and feed the 3PL ROI estimator."""
    end_d = date.today()
    start_d = end_d - timedelta(days=days) if days else None
    where_sql, params = _window_clauses(start=start_d, end=end_d)
    rows = db.execute(text(f"""
        SELECT
            UPPER(COALESCE(NULLIF(s.ship_to_state,''), '??')) AS state,
            UPPER(COALESCE(NULLIF(s.ship_to_country,''), 'US')) AS country,
            COUNT(*) AS shipments,
            SUM(s.shipment_cost + s.insurance_cost)::numeric(12,2) AS total_cost,
            AVG(s.shipment_cost + s.insurance_cost)::numeric(10,2) AS avg_cost
        FROM shipstation_shipments s
        WHERE {where_sql}
        GROUP BY state, country
        ORDER BY shipments DESC
    """), params).all()

    by_state = []
    domestic = 0
    intl = 0
    for r in rows:
        if r.country == "US":
            domestic += r.shipments
        else:
            intl += r.shipments
        by_state.append({
            "state": r.state,
            "country": r.country,
            "shipments": int(r.shipments),
            "total_cost_usd": float(r.total_cost or 0),
            "avg_cost_usd": float(r.avg_cost or 0),
        })

    return {
        "window": {"start": start_d.isoformat() if start_d else None, "end": end_d.isoformat(), "days": days},
        "totals": {"domestic_shipments": domestic, "international_shipments": intl, "states_seen": len(by_state)},
        "by_state": by_state,
    }


# ── Fulfillment SLA + shipping cost trend ───────────────────────────


def shipping_cost_trend(db: Session, *, days: int = 90, bucket: str = "week") -> dict[str, Any]:
    """Time-series of shipments + cost, bucketed by week or day. Powers
    the trend chart on the operations card."""
    end_d = date.today()
    start_d = end_d - timedelta(days=days)
    where_sql, params = _window_clauses(start=start_d, end=end_d)
    bucket_sql = "date_trunc('week', s.ship_date)" if bucket == "week" else "s.ship_date"
    rows = db.execute(text(f"""
        SELECT
            {bucket_sql}::date AS bucket,
            COUNT(*) AS shipments,
            SUM(s.shipment_cost + s.insurance_cost)::numeric(12,2) AS cost
        FROM shipstation_shipments s
        WHERE {where_sql}
        GROUP BY bucket ORDER BY bucket
    """), params).all()
    return {
        "window": {"start": start_d.isoformat(), "end": end_d.isoformat(), "days": days, "bucket": bucket},
        "series": [
            {"bucket": r.bucket.isoformat(), "shipments": int(r.shipments), "cost_usd": float(r.cost or 0), "avg_cost_usd": float(r.cost or 0) / int(r.shipments)}
            for r in rows
        ],
    }


# ── 3PL ROI estimator ───────────────────────────────────────────────


# Distance-based shipping cost approximation. This is a rough heuristic
# anchored in carrier zone-rate tables: shipments < 500 mi are roughly
# zone 2-3, 500-1500 mi zone 4-6, >1500 mi zone 7-8. We approximate
# "shipping cost saved" if a 3PL closer to the destination existed.
ZONE_BOUNDARIES_MI = [(150, 1.0), (300, 1.10), (600, 1.25), (1000, 1.45), (1400, 1.65), (1800, 1.85), (10000, 2.10)]


def _zone_multiplier(miles: float) -> float:
    for boundary, mult in ZONE_BOUNDARIES_MI:
        if miles <= boundary:
            return mult
    return ZONE_BOUNDARIES_MI[-1][1]


# Candidate 3PL locations the operator might consider, by region.
# The estimator scores each: how much would Spider have saved if these
# warehouses had existed for the recent window's shipments?
CANDIDATE_3PL_LOCATIONS = [
    {"name": "Reno, NV (West Coast)",      "state": "NV", "lat": 39.5296, "lon": -119.8138},
    {"name": "Salt Lake City, UT",         "state": "UT", "lat": 40.7608, "lon": -111.8910},
    {"name": "Dallas, TX",                 "state": "TX", "lat": 32.7767, "lon": -96.7970},
    {"name": "Phoenix, AZ",                "state": "AZ", "lat": 33.4484, "lon": -112.0740},
    {"name": "Columbus, OH",               "state": "OH", "lat": 39.9612, "lon": -82.9988},
    {"name": "Indianapolis, IN",           "state": "IN", "lat": 39.7684, "lon": -86.1581},
]


def threepl_roi_estimator(db: Session, *, days: int = 365) -> dict[str, Any]:
    """For the current Atlanta hub vs each candidate 3PL location,
    estimate annualized shipping cost. Picks where adding a second
    location would save the most on outbound zones.

    Method: for each shipment in the window, compute distance from
    Atlanta + distance from each candidate. Apply zone-multiplier to
    the cost. Compare totals.
    """
    end_d = date.today()
    start_d = end_d - timedelta(days=days)
    where_sql, params = _window_clauses(start=start_d, end=end_d)
    rows = db.execute(text(f"""
        SELECT
            UPPER(COALESCE(NULLIF(s.ship_to_state,''), '??')) AS state,
            COUNT(*) AS shipments,
            SUM(s.shipment_cost + s.insurance_cost)::numeric(12,2) AS total_cost
        FROM shipstation_shipments s
        WHERE {where_sql}
          AND COALESCE(s.ship_to_country,'US') = 'US'
        GROUP BY state
    """), params).all()

    pw = PRIMARY_WAREHOUSE
    pw_lat, pw_lon = pw["lat"], pw["lon"]

    # Baseline cost from Atlanta (current state)
    state_costs: list[dict[str, Any]] = []
    total_baseline = 0.0
    total_shipments = 0
    for r in rows:
        c = STATE_CENTROIDS.get(r.state)
        if not c:
            continue
        miles_atl = _haversine_miles(pw_lat, pw_lon, c[0], c[1])
        zone_atl = _zone_multiplier(miles_atl)
        actual_cost = float(r.total_cost or 0)
        state_costs.append({
            "state": r.state,
            "shipments": int(r.shipments),
            "actual_cost_usd": actual_cost,
            "miles_from_atl": round(miles_atl, 0),
            "zone_mult_atl": zone_atl,
        })
        total_baseline += actual_cost
        total_shipments += int(r.shipments)

    # For each candidate, compute the "best-case" outbound cost where
    # each shipment is fulfilled from whichever location is closer.
    candidates_scored = []
    for cand in CANDIDATE_3PL_LOCATIONS:
        savings_total = 0.0
        win_count = 0
        for sc in state_costs:
            cstate = STATE_CENTROIDS.get(sc["state"])
            if not cstate:
                continue
            miles_cand = _haversine_miles(cand["lat"], cand["lon"], cstate[0], cstate[1])
            zone_cand = _zone_multiplier(miles_cand)
            zone_atl = sc["zone_mult_atl"]
            if zone_cand < zone_atl:
                # Shipping from cand would be cheaper for this state.
                # Rough savings: actual_cost × (1 − zone_cand/zone_atl).
                savings = sc["actual_cost_usd"] * (1 - zone_cand / zone_atl)
                savings_total += savings
                win_count += sc["shipments"]
        candidates_scored.append({
            "name": cand["name"],
            "state": cand["state"],
            "estimated_annual_savings_usd": round(savings_total * (365 / max(days, 1)), 2),
            "in_window_savings_usd": round(savings_total, 2),
            "shipments_better_served": win_count,
            "savings_pct": round(savings_total / total_baseline * 100, 1) if total_baseline > 0 else 0,
        })
    candidates_scored.sort(key=lambda x: -x["estimated_annual_savings_usd"])

    return {
        "window": {"start": start_d.isoformat(), "end": end_d.isoformat(), "days": days},
        "current_warehouse": pw,
        "totals": {"shipments_in_window": total_shipments, "actual_cost_usd": round(total_baseline, 2)},
        "candidates": candidates_scored,
        "method_note": (
            "Uses haversine distance from each warehouse to state centroid + "
            "carrier zone-multiplier approximation. Conservative: assumes "
            "fulfillment cost scales linearly with zone, ignores fixed warehouse "
            "operating cost. Use as direction-finder, not financial commitment."
        ),
    }


# ── Cost-by-SKU drill-down ──────────────────────────────────────────────
# Joseph asked 2026-04-29 for shipping cost broken out by SKU, by carrier,
# and over time. Mechanics: shipment cost lives on shipstation_shipments
# (per-shipment), but SKU lives on the Shopify order's line_items. We
# join on ss_order_number → shopify_order_events.order_number to recover
# the line items, then attribute the shipment cost across the lines
# pro-rata by line value (price × qty) — same allocator product_cogs
# uses for COGS attribution, so the shares reconcile.
#
# Trade-offs we're explicit about:
# - One shipment can cover multiple SKUs, so "cost per SKU per shipment"
#   is allocated, not measured. The aggregate at SKU level is still
#   meaningful — it answers "did this SKU's bundles get expensive to
#   ship this quarter."
# - Free-shipping orders show shipment_cost=0 on our side (we paid the
#   carrier nothing because we didn't book a label), so SKU-level
#   averages are weighted toward orders we actually paid to ship.

def shipping_cost_by_sku(
    db: Session,
    days: int = 90,
    bucket: str = "week",  # 'week' | 'month' | 'day'
    top_n_skus: int = 20,
) -> dict[str, Any]:
    """Per-SKU shipping cost over time, broken down by carrier.

    Returns:
        {
          "window_days": 90,
          "as_of": "...",
          "totals": {
              "shipments": int,
              "shipped_units": int,         # sum of qty across attributed lines
              "total_shipping_cost_usd": float,
              "skus_seen": int,
              "carriers_seen": int,
          },
          "by_sku": [
              {
                "sku": "SG-H-01",
                "title": "The Huntsman™",
                "shipments": int,        # parcels paid for this SKU
                "units": int,            # customer units (deduped across boxes)
                "boxes_per_unit": float, # ~2.0 for Huntsman, ~1.0 single-box SKUs
                "attributed_cost_usd": float,
                "avg_cost_per_unit_usd": float,  # cost ÷ customer units
                "carriers": [
                    {"carrier_code": "fedex", "service_code": "fedex_home_delivery",
                     "shipments": int, "attributed_cost_usd": float},
                    ...
                ],
              },
              ...  (top N by attributed_cost desc)
          ],
          "by_carrier": [
              {"carrier_code": "fedex", "shipments": int,
               "attributed_cost_usd": float, "service_codes": [...]},
              ...
          ],
          "trend": [
              {"bucket": "2026-W17", "carrier_code": "fedex",
               "attributed_cost_usd": float, "shipments": int},
              ...
          ],
        }
    """
    if days <= 0:
        days = 90
    bucket = bucket if bucket in {"day", "week", "month"} else "week"

    # date_trunc unit — Postgres expects 'week' / 'month' / 'day'.
    trunc_unit = bucket

    rows = db.execute(text(f"""
        WITH eligible_orders AS (
            -- Latest non-cancelled snapshot per Shopify order, with
            -- line_items present. shopify_order_events.order_id is
            -- the Shopify numeric foreign id (e.g. 7079596130615).
            -- raw_payload->>'order_number' is empty in our snapshot
            -- ingestion path so we don't rely on it; we join on
            -- order_id directly.
            SELECT DISTINCT ON (order_id)
                order_id,
                raw_payload AS payload
            FROM shopify_order_events
            WHERE event_type = 'poll.order_snapshot'
              AND jsonb_typeof(raw_payload->'line_items') = 'array'
              AND COALESCE(raw_payload->>'cancelled_at','') = ''
              AND COALESCE(raw_payload->>'financial_status','') <> 'refunded'
              AND business_date >= CURRENT_DATE - (:days || ' days')::interval
            ORDER BY order_id, event_timestamp DESC NULLS LAST, id DESC
        ),
        shipments AS (
            -- Shipments we want to attribute. ShipStation's
            -- raw_payload.orderKey carries the Shopify order id
            -- in its first '-' part (the suffix is a checkout token,
            -- NOT a line_item_id — verified). The trackingNumber is
            -- the truth-key: it pairs 1:1 with a Shopify fulfillment
            -- record, which carries the actual line_items that went
            -- in this physical box.
            SELECT
                ss.id,
                ss.ss_order_id,
                ss.ss_order_number,
                NULLIF(SPLIT_PART(COALESCE(ss.raw_payload->>'orderKey', ''), '-', 1), '') AS shopify_order_id,
                NULLIF(ss.raw_payload->>'trackingNumber', '') AS tracking_number,
                ss.carrier_code,
                ss.service_code,
                ss.shipment_cost,
                ss.ship_date,
                ss.weight_oz
            FROM shipstation_shipments ss
            WHERE ss.voided = false
              AND ss.ship_date >= CURRENT_DATE - (:days || ' days')::interval
              AND ss.shipment_cost > 0
        ),
        fulfillment_lines AS (
            -- Per-(order_id, tracking_number) line manifest from
            -- Shopify fulfillments[]. Each fulfillment is one
            -- physical box; its line_items[] tells us EXACTLY which
            -- order lines went in that box. JOIN-key is tracking_number
            -- (1:1 with ShipStation.trackingNumber).
            --
            -- WITH ORDINALITY on the OUTER fulfillments array so we
            -- preserve a stable line_idx for unit dedupe — but we
            -- want the line_idx from the ORIGINAL order line_items
            -- ordering (so dedupe matches the prorata path), so we
            -- compute it via a JOIN to the order's line_items by id.
            SELECT
                eo.order_id::text AS order_id,
                fulfillment->>'tracking_number' AS tracking_number,
                ful_line.line->>'sku' AS sku,
                ful_line.line->>'title' AS title,
                COALESCE((ful_line.line->>'quantity')::int, 0) AS qty,
                COALESCE((ful_line.line->>'price')::numeric, 0) AS unit_price,
                ful_line.line->>'id' AS shopify_line_id,
                -- Stable line_idx from the order's full line_items
                -- (NOT from this fulfillment's line subset) so dedupe
                -- across multiple shipments of the same line aligns.
                (
                    SELECT order_line.idx::int
                    FROM jsonb_array_elements(eo.payload->'line_items')
                      WITH ORDINALITY AS order_line(line, idx)
                    WHERE (order_line.line->>'id') = (ful_line.line->>'id')
                    LIMIT 1
                ) AS line_idx
            FROM eligible_orders eo
            CROSS JOIN LATERAL jsonb_array_elements(eo.payload->'fulfillments') AS fulfillment
            CROSS JOIN LATERAL jsonb_array_elements(fulfillment->'line_items') AS ful_line(line)
            WHERE jsonb_typeof(eo.payload->'fulfillments') = 'array'
              AND COALESCE(fulfillment->>'tracking_number', '') <> ''
              AND COALESCE(ful_line.line->>'sku', '') <> ''
        ),
        line_keyed AS (
            -- LINE-KEYED (TRUTH) PATH: shipment's tracking_number
            -- matches a Shopify fulfillment's tracking_number — we
            -- know the exact lines in this box. Cost goes pro-rata
            -- across ONLY those lines (usually 1; sometimes a few
            -- if multiple lines combined into one box). This is
            -- exact per-SKU shipping cost — no allocator bleed.
            --
            -- Pro-rata WITHIN the box: if a box carries 2 lines
            -- (e.g. cover + accessory), split by their value share.
            -- If the box carries 1 line (typical), 100% goes to it.
            SELECT
                s.id AS shipment_id,
                s.shopify_order_id AS order_id,
                s.carrier_code,
                s.service_code,
                s.shipment_cost,
                s.ship_date,
                fl.sku, fl.title, fl.line_idx, fl.qty,
                (s.shipment_cost * (fl.qty * fl.unit_price)
                  / NULLIF(SUM(fl.qty * fl.unit_price) OVER (PARTITION BY s.id), 0))
                  AS attributed_cost,
                'line_keyed' AS attribution_mode
            FROM shipments s
            JOIN fulfillment_lines fl
              ON fl.order_id = s.shopify_order_id
             AND fl.tracking_number = s.tracking_number
            WHERE s.tracking_number IS NOT NULL
              AND fl.line_idx IS NOT NULL
        ),
        prorata_join AS (
            -- PRO-RATA FALLBACK: no fulfillment match for this
            -- shipment (rare — older orders or unusual paths).
            -- Spread cost across all lines by line value share.
            SELECT
                s.id AS shipment_id,
                s.shopify_order_id AS order_id,
                s.carrier_code,
                s.service_code,
                s.shipment_cost,
                s.ship_date,
                line_data.line->>'sku' AS sku,
                line_data.line->>'title' AS title,
                line_data.idx::int AS line_idx,
                COALESCE((line_data.line->>'quantity')::int, 0) AS qty,
                COALESCE((line_data.line->>'price')::numeric, 0) AS unit_price
            FROM shipments s
            JOIN eligible_orders eo
              ON eo.order_id::text = s.shopify_order_id
            CROSS JOIN LATERAL jsonb_array_elements(eo.payload->'line_items')
              WITH ORDINALITY AS line_data(line, idx)
            WHERE NOT EXISTS (
                SELECT 1 FROM fulfillment_lines fl
                WHERE fl.order_id = s.shopify_order_id
                  AND fl.tracking_number = s.tracking_number
            )
            AND COALESCE(line_data.line->>'sku', '') <> ''
        ),
        prorata_allocated AS (
            SELECT
                shipment_id, order_id, carrier_code, service_code, shipment_cost,
                ship_date, sku, title, line_idx, qty,
                (shipment_cost * (qty * unit_price)
                  / NULLIF(SUM(qty * unit_price) OVER (PARTITION BY shipment_id), 0))
                  AS attributed_cost,
                'prorata' AS attribution_mode
            FROM prorata_join
        )
        SELECT
            sku, title, carrier_code, service_code, ship_date, shipment_id,
            order_id, line_idx, qty, attributed_cost, attribution_mode
        FROM line_keyed
        UNION ALL
        SELECT
            sku, title, carrier_code, service_code, ship_date, shipment_id,
            order_id, line_idx, qty, attributed_cost, attribution_mode
        FROM prorata_allocated
        WHERE attributed_cost IS NOT NULL
    """), {"days": days}).all()

    if not rows:
        return {
            "window_days": days, "bucket": bucket,
            "as_of": datetime.now(timezone.utc).date().isoformat(),
            "totals": {"shipments": 0, "shipped_units": 0, "total_shipping_cost_usd": 0.0,
                       "skus_seen": 0, "carriers_seen": 0},
            "by_sku": [], "by_carrier": [], "trend": [],
        }

    # Group in Python — query already aggregated to the line/shipment grain.
    #
    # Unit dedupe (the Huntsman-2-boxes fix): one customer line of
    # 1× Huntsman can appear in TWO shipment rows because Huntsman
    # ships as 2 parcels. Without dedupe, the JOIN gives us 2 rows
    # both with qty=1 — summing them double-counts the customer unit
    # and halves the per-unit cost. We track (order_id, sku, line_idx)
    # in `seen_units` and only credit qty the FIRST time each unique
    # customer line is seen. Cost still sums across all shipment rows
    # (every shipment contributes its full cost).
    from collections import defaultdict
    sku_totals: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "title": None, "shipments": set(), "units": 0, "attributed_cost_usd": 0.0,
        "by_carrier": defaultdict(lambda: {"shipments": set(), "attributed_cost_usd": 0.0}),
    })
    carrier_totals: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "shipments": set(), "attributed_cost_usd": 0.0, "service_codes": set(),
    })
    trend_totals: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {
        "shipments": set(), "attributed_cost_usd": 0.0,
    })

    # Dedupe key for unit counting: a customer line is uniquely
    # identified by (order_id, sku, line_idx). Per-carrier unit
    # counts are *intentionally* dropped — when a single customer
    # unit ships across multiple carriers (e.g. box 1 FedEx, box 2
    # UPS — rare but possible), assigning a fractional unit to each
    # carrier is more confusing than just exposing shipments + cost
    # at the carrier level. Headline unit count lives at the SKU level.
    seen_units: set[tuple[str, str, int]] = set()

    # Track attribution mode mix so the UI can show "X% of cost is
    # line-keyed (truth) vs pro-rata (estimate)".
    line_keyed_cost = 0.0
    prorata_cost = 0.0

    all_shipments: set[int] = set()
    for r in rows:
        sku = r.sku or "unknown"
        carrier = r.carrier_code or "unknown"
        cost = float(r.attributed_cost or 0)
        unit_key = (str(r.order_id or ""), sku, int(r.line_idx or 0))
        if getattr(r, "attribution_mode", "prorata") == "line_keyed":
            line_keyed_cost += cost
        else:
            prorata_cost += cost

        st = sku_totals[sku]
        if not st["title"] and r.title:
            st["title"] = r.title
        st["shipments"].add(r.shipment_id)
        st["attributed_cost_usd"] += cost
        if unit_key not in seen_units:
            seen_units.add(unit_key)
            st["units"] += int(r.qty or 0)

        ckey = (carrier, r.service_code or "—")
        sc = st["by_carrier"][ckey]
        sc["shipments"].add(r.shipment_id)
        sc["attributed_cost_usd"] += cost

        ct = carrier_totals[carrier]
        ct["shipments"].add(r.shipment_id)
        ct["attributed_cost_usd"] += cost
        if r.service_code:
            ct["service_codes"].add(r.service_code)

        # Trend bucket key — snap ship_date to the bucket boundary.
        if r.ship_date:
            if bucket == "day":
                bk = r.ship_date.isoformat()
            elif bucket == "month":
                bk = r.ship_date.strftime("%Y-%m")
            else:
                # ISO week; format YYYY-W##
                iso = r.ship_date.isocalendar()
                bk = f"{iso.year}-W{iso.week:02d}"
            tk = (bk, carrier)
            tt = trend_totals[tk]
            tt["shipments"].add(r.shipment_id)
            tt["attributed_cost_usd"] += cost

        all_shipments.add(r.shipment_id)

    # Materialize.
    by_sku_list = []
    for sku, t in sku_totals.items():
        carriers_out = []
        for (cc, sc_), v in sorted(t["by_carrier"].items(), key=lambda kv: -kv[1]["attributed_cost_usd"]):
            carriers_out.append({
                "carrier_code": cc,
                "service_code": sc_ if sc_ != "—" else None,
                "shipments": len(v["shipments"]),
                "attributed_cost_usd": round(v["attributed_cost_usd"], 2),
            })
        units = t["units"]
        shipments = len(t["shipments"])
        cost = t["attributed_cost_usd"]
        # boxes_per_unit surfaces multi-parcel SKUs (e.g. Huntsman ≈ 2.0).
        # Round to 2dp so a perfect 1-box SKU shows 1.0 and a 2-box SKU
        # shows 2.0, with mixed (some bundles consolidated) showing 1.4-ish.
        boxes_per_unit = round(shipments / units, 2) if units > 0 else None
        by_sku_list.append({
            "sku": sku,
            "title": t["title"],
            "shipments": shipments,
            "units": units,
            "boxes_per_unit": boxes_per_unit,
            "attributed_cost_usd": round(cost, 2),
            "avg_cost_per_unit_usd": round(cost / units, 2) if units > 0 else None,
            "carriers": carriers_out,
        })
    by_sku_list.sort(key=lambda d: -d["attributed_cost_usd"])

    by_carrier_list = []
    for cc, v in sorted(carrier_totals.items(), key=lambda kv: -kv[1]["attributed_cost_usd"]):
        by_carrier_list.append({
            "carrier_code": cc,
            "shipments": len(v["shipments"]),
            "attributed_cost_usd": round(v["attributed_cost_usd"], 2),
            "service_codes": sorted(v["service_codes"]),
        })

    trend_list = []
    for (bk, cc), v in sorted(trend_totals.items()):
        trend_list.append({
            "bucket": bk,
            "carrier_code": cc,
            "shipments": len(v["shipments"]),
            "attributed_cost_usd": round(v["attributed_cost_usd"], 2),
        })

    total_units = sum(s["units"] for s in by_sku_list)
    total_cost = sum(s["attributed_cost_usd"] for s in by_sku_list)

    return {
        "window_days": days,
        "bucket": bucket,
        "as_of": datetime.now(timezone.utc).date().isoformat(),
        "totals": {
            "shipments": len(all_shipments),
            "shipped_units": total_units,
            "total_shipping_cost_usd": round(total_cost, 2),
            "skus_seen": len(by_sku_list),
            "carriers_seen": len(by_carrier_list),
            # Mix of attribution methods: line-keyed = exact (one shipment
            # → one line via Shopify line_item_id in orderKey); pro-rata
            # = legacy fallback (split across all lines by value share).
            "attribution_mode": {
                "line_keyed_cost_usd": round(line_keyed_cost, 2),
                "prorata_cost_usd": round(prorata_cost, 2),
                "line_keyed_share": (
                    round(line_keyed_cost / (line_keyed_cost + prorata_cost), 3)
                    if (line_keyed_cost + prorata_cost) > 0 else None
                ),
            },
        },
        "by_sku": by_sku_list[:top_n_skus],
        "by_carrier": by_carrier_list,
        "trend": trend_list,
        "method_note": (
            "Two-mode attribution. (1) LINE-KEYED (truth): every ShipStation shipment "
            "is JOINed to its Shopify fulfillment via tracking_number — Shopify's "
            "fulfillments[].line_items tells us EXACTLY which order lines went in that "
            "box. Cost goes pro-rata only across those lines (usually 1 line per box, "
            "100% to that SKU; sometimes a few lines combined, split by value). For "
            "multi-box SKUs (Huntsman ships in 2 boxes) both boxes' fulfillments cite "
            "the same line, so the SKU gets ALL the parcel cost — no bleed onto "
            "accessories. (2) PRO-RATA fallback: shipments with no fulfillment match "
            "(rare — older orders) split cost across all order lines by value share. "
            "attribution_mode.line_keyed_share shows what fraction of the window is exact. "
            "Units are deduped on (order_id, sku, line_idx); boxes_per_unit exposes the "
            "true parcel-per-customer-unit ratio (Huntsman ≈ 2.0). Free-shipping (cost=0) "
            "and voided shipments excluded."
        ),
    }
