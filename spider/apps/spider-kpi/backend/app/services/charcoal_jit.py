"""Charcoal JIT forecaster — dry-run scheduler for auto-ship timing.

The UI already has a client-side forecast on the "JIT program" tab.
This module is the SERVER-SIDE twin that runs daily, writes back
``last_forecast_json`` + ``next_ship_after`` to every active
``CharcoalJITSubscription``, and serves those numbers to the
enrollment list.

It does NOT create Shopify orders. That trigger stays manual until
Joseph is confident the predictions are sensible dry-run.

The thermal model mirrors ``frontend/src/lib/charcoalModel.ts`` —
kept in sync manually for now; a future refactor could generate the
TS from the Python (or the reverse).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import CharcoalJITSubscription, PartnerProduct, ShopifyOrderEvent, TelemetrySession

logger = logging.getLogger(__name__)


# ── Thermal model (mirror of the TS version) ─────────────────────────

LUMP_BTU_PER_LB = 9_000
BRIQUETTE_BTU_PER_LB = 6_500
COMBUSTION_EFFICIENCY = 0.60

# CONUS monthly climate normal (°F), index 0 = January.
CONUS_MONTHLY_F = [34, 37, 45, 54, 63, 72, 76, 75, 68, 56, 45, 36]


def thermal_demand_btu_per_hr(avg_pit_temp_f: float) -> float:
    """BTU/hr required to hold the given pit temp. Smooth quadratic fit
    to empirical kettle heat-loss anchors. Clamps 180-600°F."""
    t = max(180.0, min(600.0, avg_pit_temp_f))
    dt = t - 60.0
    return 0.02 * dt * dt + 45.0 * dt + 1_500.0


def estimate_ambient_f(cook_date: datetime, lat_deg: Optional[float] = None) -> float:
    """Season-based ambient estimate with optional latitude adjust."""
    base = CONUS_MONTHLY_F[cook_date.month - 1]
    if lat_deg is None:
        return float(base)
    import math
    lat_delta = lat_deg - 40.0
    winter_weight = abs(math.cos((cook_date.month - 6) * math.pi / 6.0))
    per_degree = 0.8 + 0.4 * winter_weight
    return float(base - lat_delta * per_degree)


def session_fuel_lb(
    duration_hours: float,
    avg_temp_f: Optional[float],
    efficiency: float = COMBUSTION_EFFICIENCY,
) -> tuple[float, float]:
    """Return (lump_lb, briquette_lb) for a cook session."""
    if duration_hours <= 0 or avg_temp_f is None or avg_temp_f <= 0:
        return (0.0, 0.0)
    delivered_btu = thermal_demand_btu_per_hr(avg_temp_f) * duration_hours
    fuel_btu = delivered_btu / max(0.1, efficiency)
    return (fuel_btu / LUMP_BTU_PER_LB, fuel_btu / BRIQUETTE_BTU_PER_LB)


# ── Address lookup: MAC / email → Shopify ship zip + lat/lon ─────────


def lookup_shipping_address(
    db: Session,
    *,
    user_key: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Find the most-recent Shopify order for a customer (matched by
    email or user_key) and return the normalized shipping address.
    Returns None if no match.

    ``user_key`` is expected to be the customer's email in most cases
    — that's how we join to Shopify since we don't yet have a user-id
    bridge between the app backend and Shopify.
    """
    if not user_key:
        return None
    ukey = user_key.strip().lower()
    if "@" not in ukey:
        # Not an email — we can't match Shopify orders yet. TODO: once
        # app-side user records link to Shopify customer_id, add that path.
        return None

    # Look in normalized_payload.customer_email first (we set that on
    # every order snapshot going forward), then fall back to scanning
    # raw_payload for legacy rows.
    row = db.execute(text("""
        SELECT normalized_payload, raw_payload, event_timestamp
        FROM shopify_order_events
        WHERE event_type = 'poll.order_snapshot'
          AND (
              lower(normalized_payload->>'customer_email') = :email
              OR lower(raw_payload->>'email') = :email
              OR lower(raw_payload->'customer'->>'email') = :email
          )
        ORDER BY event_timestamp DESC NULLS LAST
        LIMIT 1
    """), {"email": ukey}).first()

    if row is None:
        return None
    normalized, raw, _ts = row
    shipping = (normalized or {}).get("shipping_address") or {}
    if not shipping:
        raw_addr = (raw or {}).get("shipping_address") or {}
        if raw_addr:
            shipping = {
                "zip": raw_addr.get("zip"),
                "city": raw_addr.get("city"),
                "province_code": raw_addr.get("province_code"),
                "country_code": raw_addr.get("country_code"),
                "latitude": raw_addr.get("latitude"),
                "longitude": raw_addr.get("longitude"),
            }
    return shipping or None


# ── Forecast a single subscription ───────────────────────────────────


def _collect_session_fuel(
    db: Session,
    device_id: str,
    lookback_days: int,
) -> list[tuple[float, float, datetime]]:
    """Return per-session (lump_lb, briquette_lb, session_start) for the
    trailing window, using target_temp as fallback when actual isn't set."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    rows = db.execute(
        select(
            TelemetrySession.session_duration_seconds,
            TelemetrySession.target_temp,
            TelemetrySession.actual_temp_time_series,
            TelemetrySession.session_start,
        )
        .where(TelemetrySession.device_id == device_id)
        .where(TelemetrySession.session_start >= cutoff)
        .where(TelemetrySession.session_duration_seconds >= 300)
    ).all()
    out: list[tuple[float, float, datetime]] = []
    for dur_s, tgt, series, start in rows:
        if not dur_s or not start:
            continue
        avg_actual = None
        if isinstance(series, list) and series:
            vals = []
            for s in series:
                try:
                    v = float(s.get("v"))
                except (AttributeError, TypeError, ValueError):
                    continue
                if 0 < v < 1000:
                    vals.append(v)
            if vals:
                avg_actual = sum(vals) / len(vals)
        avg_temp = avg_actual if avg_actual is not None else tgt
        if avg_temp is None:
            continue
        lump, briq = session_fuel_lb(dur_s / 3600.0, float(avg_temp))
        out.append((lump, briq, start))
    return out


def forecast_subscription(
    db: Session,
    sub: CharcoalJITSubscription,
    *,
    lookback_days: int = 90,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Run the forecast for one subscription. Writes back
    ``last_forecast_json`` + ``next_ship_after``. Returns the payload."""
    now = now or datetime.now(timezone.utc)
    if not sub.device_id:
        # Scheduler hasn't re-keyed yet; skip but record the state.
        payload = {
            "computed_at": now.isoformat(),
            "status": "skipped_no_device_id",
            "note": "Subscription has no resolved device_id yet — waiting for telemetry or re-key.",
        }
        sub.last_forecast_json = payload
        sub.next_ship_after = None
        return payload

    fuel_rows = _collect_session_fuel(db, sub.device_id, lookback_days)
    if not fuel_rows:
        payload = {
            "computed_at": now.isoformat(),
            "status": "no_sessions",
            "lookback_days": lookback_days,
            "note": "No cook sessions in the lookback window. Device hasn't cooked — no shipment scheduled.",
        }
        sub.last_forecast_json = payload
        sub.next_ship_after = None
        return payload

    weeks = lookback_days / 7.0
    total_lump = sum(r[0] for r in fuel_rows)
    total_briq = sum(r[1] for r in fuel_rows)
    lb_per_week = (total_lump if sub.fuel_preference == "lump" else total_briq) / weeks

    # Resolve the partner product (if any) so the financial model can
    # use today's retail price. Subscription.bag_size_lb is the
    # authoritative bag size — if a partner product is linked AND has
    # a bag_size, we honor the partner's; otherwise keep what the user
    # chose at enrollment.
    partner_product = None
    if sub.partner_product_id:
        partner_product = db.get(PartnerProduct, sub.partner_product_id)

    if lb_per_week <= 0:
        payload = {
            "computed_at": now.isoformat(),
            "status": "zero_burn",
            "lookback_days": lookback_days,
            "cooks_in_window": len(fuel_rows),
            "note": "Burn rate computed to zero — possible cold window or model edge case.",
        }
        sub.last_forecast_json = payload
        sub.next_ship_after = None
        return payload

    # Effective bag size: partner product's bag_size wins if present.
    effective_bag_lb = (
        partner_product.bag_size_lb
        if partner_product and partner_product.bag_size_lb
        else sub.bag_size_lb
    )
    lb_per_day = lb_per_week / 7.0
    days_per_bag = effective_bag_lb / lb_per_day
    next_ship_in_days = max(0.0, days_per_bag - sub.lead_time_days - sub.safety_stock_days)
    next_ship_after = now + timedelta(days=next_ship_in_days)

    upcoming = []
    for i in range(6):
        d = now + timedelta(days=next_ship_in_days + days_per_bag * i)
        upcoming.append(d.date().isoformat())

    # ── Financial model ───────────────────────────────────────────
    # Customer pays the retail price (partner's storefront price).
    # Spider Grills takes margin_pct; remainder flows to the partner.
    # No payment processing fees / shipping modeled here yet — those
    # plug in when the live trigger lands.
    financial = None
    if partner_product is not None and partner_product.retail_price_usd > 0:
        retail = float(partner_product.retail_price_usd)
        margin_pct = float(sub.margin_pct or 0.0)
        per_ship_revenue = retail
        per_ship_margin = retail * (margin_pct / 100.0)
        per_ship_partner_payout = retail - per_ship_margin
        shipments_per_year = (lb_per_week * 52.0) / max(1, effective_bag_lb)
        financial = {
            "partner": partner_product.partner,
            "partner_product_title": partner_product.title,
            "bag_size_lb": effective_bag_lb,
            "retail_price_usd": round(retail, 2),
            "margin_pct": round(margin_pct, 2),
            "per_ship_revenue_usd": round(per_ship_revenue, 2),
            "per_ship_margin_usd": round(per_ship_margin, 2),
            "per_ship_partner_payout_usd": round(per_ship_partner_payout, 2),
            "shipments_per_year": round(shipments_per_year, 2),
            "annual_revenue_usd": round(shipments_per_year * per_ship_revenue, 2),
            "annual_margin_usd": round(shipments_per_year * per_ship_margin, 2),
            "annual_partner_payout_usd": round(shipments_per_year * per_ship_partner_payout, 2),
        }

    payload = {
        "computed_at": now.isoformat(),
        "status": "ok",
        "lookback_days": lookback_days,
        "cooks_in_window": len(fuel_rows),
        "fuel_preference": sub.fuel_preference,
        "bag_size_lb": effective_bag_lb,
        "lead_time_days": sub.lead_time_days,
        "safety_stock_days": sub.safety_stock_days,
        "lb_per_week": round(lb_per_week, 3),
        "lb_per_day": round(lb_per_day, 4),
        "days_per_bag": round(days_per_bag, 2),
        "next_ship_in_days": round(next_ship_in_days, 2),
        "upcoming_ship_dates": upcoming,
        "annual_bags_est": round(lb_per_week * 52.0 / max(1, effective_bag_lb), 2),
        "financial": financial,
    }
    # Also include the cross-fuel number so the UI can show "if you
    # switched to briquettes you'd need X lb/week instead." Useful if
    # Joseph wants to visualize fuel-switch cost.
    payload["cross_fuel_lb_per_week"] = round(
        (total_briq if sub.fuel_preference == "lump" else total_lump) / weeks,
        3,
    )

    sub.last_forecast_json = payload
    sub.next_ship_after = next_ship_after
    return payload


# ── Scheduler tick ───────────────────────────────────────────────────


def run_daily_forecast_pass(db: Session) -> dict[str, Any]:
    """Daily job: re-forecast every non-cancelled subscription. Also
    auto-fill shipping_address from Shopify orders where the
    subscription has a user_key (email) but no shipping_zip yet."""
    now = datetime.now(timezone.utc)
    subs = db.execute(
        select(CharcoalJITSubscription).where(
            CharcoalJITSubscription.status != "cancelled"
        )
    ).scalars().all()

    stats = {
        "considered": len(subs),
        "forecasted_ok": 0,
        "skipped_no_device_id": 0,
        "no_sessions": 0,
        "zero_burn": 0,
        "shipping_address_backfilled": 0,
    }

    for sub in subs:
        # Auto-fill shipping address from Shopify if we don't have it yet
        if not sub.shipping_zip and sub.user_key:
            addr = lookup_shipping_address(db, user_key=sub.user_key)
            if addr and addr.get("zip"):
                sub.shipping_zip = str(addr["zip"])
                if addr.get("latitude") is not None:
                    try: sub.shipping_lat = float(addr["latitude"])
                    except (TypeError, ValueError): pass
                if addr.get("longitude") is not None:
                    try: sub.shipping_lon = float(addr["longitude"])
                    except (TypeError, ValueError): pass
                stats["shipping_address_backfilled"] += 1

        # Re-key synthetic mac:xxx device_ids if telemetry has arrived
        if sub.device_id is None and sub.mac_normalized:
            row = db.execute(text("""
                SELECT device_id FROM telemetry_stream_events
                WHERE lower(raw_payload->'device_data'->'reported'->>'mac') = :mac
                ORDER BY sample_timestamp DESC NULLS LAST
                LIMIT 1
            """), {"mac": sub.mac_normalized}).scalar()
            if row:
                sub.device_id = row

        # Run the forecast
        result = forecast_subscription(db, sub, now=now)
        s = result.get("status", "")
        if s == "ok": stats["forecasted_ok"] += 1
        elif s == "skipped_no_device_id": stats["skipped_no_device_id"] += 1
        elif s == "no_sessions": stats["no_sessions"] += 1
        elif s == "zero_burn": stats["zero_burn"] += 1

    db.commit()
    return {"computed_at": now.isoformat(), **stats}
