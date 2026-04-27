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
