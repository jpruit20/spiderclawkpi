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
import threading
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import CharcoalJITSubscription, PartnerProduct, ShopifyOrderEvent, TelemetrySession
from app.services.product_taxonomy import (
    build_huntsman_device_ids,
    build_t2_max_by_device,
    classify_product,
)

logger = logging.getLogger(__name__)


# ── Process-local TTL cache for the cohort burn pool ─────────────────
#
# compute_cohort_model() used to re-query + re-decode every JSONB
# actual_temp_time_series (potentially hundreds of samples per session,
# 17K+ sessions in a 90d window) on every slider move. One user
# dragging a slider would pin the single uvicorn worker for 10+ s
# and nginx would 502.
#
# Only ``lookback_days`` actually forces a DB re-query — families,
# min_cooks, target_percentile_floor, signup_pct, SKU, margin, churn,
# horizon are all pure post-hoc arithmetic. So we cache the per-device
# burn pool keyed by lookback_days and serve 99% of slider moves from
# memory.
#
# 5-minute TTL lines up with the existing product_taxonomy helper and
# with how long a user actually sits on this page.

_BURN_POOL_TTL_SEC = 300
_burn_pool_cache: dict[int, tuple[float, list[dict[str, Any]]]] = {}
_burn_pool_lock = threading.Lock()


def _build_device_burn_pool(
    db: Session,
    *,
    lookback_days: int,
    now: datetime,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Pull every qualifying session once and reduce to per-device
    monthly burn (both fuel types). This is the expensive step: JSONB
    temp-series decode for every session in the window.

    Returns a list of:
        {
          "device_id": str,
          "product_family": str,
          "sessions_in_window": int,
          "lump_lb_per_month": float,
          "briq_lb_per_month": float,
        }

    Cached process-locally with a 5-minute TTL keyed by lookback_days
    — families/min_cooks/targeting/signup/margin/churn/horizon/SKU are
    post-hoc filters or arithmetic, so they do NOT invalidate this.

    ``force=True`` bypasses the cache check (but still writes). Used
    by the scheduler warmer so the cache never goes stale at the exact
    moment a user hits the endpoint.
    """
    cache_key = int(lookback_days)
    nowsec = _time.monotonic()
    if not force:
        with _burn_pool_lock:
            hit = _burn_pool_cache.get(cache_key)
            if hit is not None and (nowsec - hit[0]) < _BURN_POOL_TTL_SEC:
                return hit[1]

    cutoff = now - timedelta(days=lookback_days)

    # Aggregate down to ONE ROW PER DEVICE entirely in Postgres. The
    # 2026-04-22 fix (3a399b5) moved JSONB averaging into PG but still
    # returned one row per session (17-34K rows) and did the fuel math
    # in Python. Each warmer tick churned ~250K Python objects through
    # glibc's arena allocator and, on Linux, those arenas never return
    # to the OS without an explicit malloc_trim — so RSS grew ~500 MB
    # per tick until the kernel OOM-killed uvicorn. Doing the GROUP BY
    # + fuel math in PG means Python only ever sees ~2-3K rows per
    # device and the only per-session object work happens server-side
    # in PG working memory (which is bounded and released cleanly).
    #
    # Thermal math mirrors thermal_demand_btu_per_hr + session_fuel_lb
    # below. Keep them in sync if the constants ever move.
    rows = db.execute(text("""
        WITH per_session AS (
            SELECT
                ts.device_id,
                ts.grill_type,
                ts.firmware_version,
                ts.session_start,
                ts.session_duration_seconds::float AS dur_s,
                COALESCE(
                    CASE WHEN jsonb_typeof(ts.actual_temp_time_series) = 'array' THEN (
                        SELECT AVG((elem->>'v')::float)
                        FROM jsonb_array_elements(ts.actual_temp_time_series) elem
                        WHERE jsonb_typeof(elem) = 'object'
                          AND (elem ? 'v')
                          AND (elem->>'v') ~ '^-?[0-9]+(\\.[0-9]+)?$'
                          AND (elem->>'v')::float > 0
                          AND (elem->>'v')::float < 1000
                    ) ELSE NULL END,
                    ts.target_temp::float
                ) AS avg_temp
            FROM telemetry_sessions ts
            WHERE ts.device_id IS NOT NULL
              AND ts.device_id NOT LIKE 'mac:%'
              AND ts.session_start IS NOT NULL
              AND ts.session_start >= :cutoff
              AND ts.session_duration_seconds >= 300
        ), fuel AS (
            SELECT
                device_id, grill_type, firmware_version, session_start, dur_s, avg_temp,
                -- dt = clamp(avg_temp, 180..600) - 60
                (LEAST(600.0, GREATEST(180.0, avg_temp)) - 60.0) AS dt
            FROM per_session
            WHERE avg_temp IS NOT NULL AND avg_temp > 0 AND dur_s > 0
        ), fuel_lb AS (
            SELECT
                device_id, grill_type, firmware_version, session_start,
                -- btu_delivered = (0.02*dt^2 + 45*dt + 1500) * hours
                -- fuel_btu = btu_delivered / 0.60
                -- lump_lb = fuel_btu / 9000 ; briq_lb = fuel_btu / 6500
                (((0.02 * dt * dt + 45.0 * dt + 1500.0) * (dur_s / 3600.0) / 0.60) / 9000.0) AS lump_lb,
                (((0.02 * dt * dt + 45.0 * dt + 1500.0) * (dur_s / 3600.0) / 0.60) / 6500.0) AS briq_lb
            FROM fuel
        )
        SELECT
            device_id,
            -- Grill type + firmware from the LATEST session in the window.
            (array_agg(grill_type       ORDER BY session_start DESC NULLS LAST))[1] AS grill_type,
            (array_agg(firmware_version ORDER BY session_start DESC NULLS LAST))[1] AS firmware_version,
            COUNT(*)       AS sessions_in_window,
            SUM(lump_lb)   AS lump_sum,
            SUM(briq_lb)   AS briq_sum
        FROM fuel_lb
        GROUP BY device_id
    """), {"cutoff": cutoff}).all()

    huntsman_ids = build_huntsman_device_ids(db)
    t2_max_map = build_t2_max_by_device(db)

    scale = 30.0 / float(lookback_days) if lookback_days > 0 else 0.0
    pool: list[dict[str, Any]] = []
    for dev, grill, fw, count, lump_sum, briq_sum in rows:
        family = classify_product(
            grill, fw,
            device_id=dev,
            huntsman_device_ids=huntsman_ids,
            t2_max=t2_max_map.get(dev),
        )
        pool.append({
            "device_id": dev,
            "product_family": family,
            "sessions_in_window": int(count),
            "lump_lb_per_month": float(lump_sum or 0.0) * scale,
            "briq_lb_per_month": float(briq_sum or 0.0) * scale,
        })

    # Drop the result list and close the implicit transaction before we
    # stash the cache. SQLAlchemy would release on scope exit anyway,
    # but being explicit bounds the connection's result-buffer lifetime
    # to this function — matters when the warmer calls us back-to-back.
    del rows
    try:
        db.rollback()
    except Exception:
        pass

    with _burn_pool_lock:
        _burn_pool_cache[cache_key] = (nowsec, pool)
    return pool


def invalidate_cohort_burn_pool_cache() -> None:
    """Drop all cached burn pools. Called after data imports that would
    change the window (e.g. a new telemetry backfill). Also handy for
    tests."""
    with _burn_pool_lock:
        _burn_pool_cache.clear()


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


# ── Cohort economic modeling (pre-beta feasibility tool) ─────────────
#
# Purpose: let Joseph pick a subset of the active fleet, assume an
# opt-in rate + SKU + margin, and see projected monthly GMV, Spider
# Grills margin, JD payout, shipments, and pounds. This is purely
# internal modeling — we haven't gone live with JIT yet and want to
# pressure-test the unit economics before enrollment opens.
#
# Burn rate per device is derived from the same thermal model the
# per-subscription forecaster uses, so the numbers are continuous with
# live JIT math once we flip it on.
#
# Shipping is explicitly excluded from the margin math: Jealous Devil
# ships directly from their supply chain and eats the shipping cost.
# We never touch the charcoal physically. If that assumption ever
# changes, the one place to add it is ``_compute_cohort_totals``.


def _percentile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolated percentile helper. ``q`` in [0, 1].
    Returns 0.0 on empty input rather than raising — callers expect a
    stable shape even when the cohort is empty."""
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    idx = q * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def compute_cohort_model(
    db: Session,
    *,
    product_families: Optional[list[str]] = None,
    min_cooks_in_window: int = 0,
    lookback_days: int = 90,
    target_percentile_floor: float = 0.0,
    signup_pct: float = 15.0,
    partner_product_id: Optional[int] = None,
    margin_pct: float = 10.0,
    monthly_churn_pct: float = 0.0,
    horizon_months: int = 12,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Core cohort modeler.

    Two-stage cohort definition:
      1. **Addressable** — every active device matching
         ``product_families`` + ``min_cooks_in_window`` in the
         ``lookback_days`` window. This is the "market".
      2. **Targeted** — the subset of the addressable pool whose
         monthly burn rate sits at or above
         ``target_percentile_floor`` (e.g. 75 = top 25% by burn).
         ``signup_pct`` applies to this narrower pool, NOT to the
         whole addressable market. Per-subscriber burn rate also uses
         the targeted slice's mean — not the overall mean — because
         JIT adoption self-selects heavy users and the conditional
         mean is much higher than the unconditional mean.

    That distinction swings the numbers a lot: at 15% signup the
    overall-mean model projects SG margin of ~$700/mo, but the same
    15% applied to the top quartile with the top-quartile's
    conditional mean projects very differently. Toggle
    ``target_percentile_floor`` between 0, 50, 75, 90 to see it.

    Applies ``monthly_churn_pct`` geometric decay over ``horizon_months``
    and the SKU's retail × ``margin_pct`` to get GMV / SG margin / JD
    payout. No side effects — safe to spam on every slider change.
    """
    now = now or datetime.now(timezone.utc)
    lookback_days = max(7, min(int(lookback_days), 365))
    horizon_months = max(1, min(int(horizon_months), 60))
    signup_pct = max(0.0, min(float(signup_pct), 100.0))
    monthly_churn_pct = max(0.0, min(float(monthly_churn_pct), 50.0))
    margin_pct = max(0.0, min(float(margin_pct), 100.0))
    target_percentile_floor = max(0.0, min(float(target_percentile_floor), 95.0))

    families_set = (
        {f.strip() for f in product_families if f and f.strip()}
        if product_families
        else None
    )

    # Resolve the SKU + its fuel preference FIRST — we need to know
    # which fuel column of the cached pool to read.
    sku = db.get(PartnerProduct, partner_product_id) if partner_product_id else None
    if sku is None:
        # Empty cohort shape so the UI can render without exploding
        return {
            "ok": False,
            "error": "partner_product_id missing or not found",
            "computed_at": now.isoformat(),
        }
    bag_size_lb = int(sku.bag_size_lb or 20)
    if bag_size_lb <= 0:
        return {
            "ok": False,
            "error": f"SKU {sku.id} has no bag_size_lb on file — set one before modeling",
            "computed_at": now.isoformat(),
        }
    fuel_pref = sku.fuel_type or "lump"

    # Heavy step (cached): pull + decode every session in the lookback
    # window. All subsequent filters are pure arithmetic on the pool,
    # so this is the ONLY part that changes per lookback value.
    pool = _build_device_burn_pool(db, lookback_days=lookback_days, now=now)

    # Apply family + min-cooks + fuel-choice filters post-hoc.
    fuel_key = "lump_lb_per_month" if fuel_pref == "lump" else "briq_lb_per_month"
    eligible: list[dict[str, Any]] = []
    for d in pool:
        if families_set is not None and d["product_family"] not in families_set:
            continue
        if d["sessions_in_window"] < min_cooks_in_window:
            continue
        lb_per_month = d[fuel_key]
        if lb_per_month <= 0:
            continue
        eligible.append({
            "device_id": d["device_id"],
            "product_family": d["product_family"],
            "sessions_in_window": d["sessions_in_window"],
            "lb_per_month": lb_per_month,
        })

    # Addressable cohort stats (everyone who matches family/cooks filter)
    lb_series = sorted(d["lb_per_month"] for d in eligible)
    families_breakdown: dict[str, int] = {}
    for d in eligible:
        families_breakdown[d["product_family"]] = families_breakdown.get(d["product_family"], 0) + 1

    mean_lb_per_month = (sum(lb_series) / len(lb_series)) if lb_series else 0.0
    cohort_stats = {
        "eligible_devices": len(eligible),
        "mean_lb_per_month_per_device": round(mean_lb_per_month, 3),
        "median_lb_per_month_per_device": round(_percentile(lb_series, 0.5), 3),
        "p25_lb_per_month_per_device": round(_percentile(lb_series, 0.25), 3),
        "p75_lb_per_month_per_device": round(_percentile(lb_series, 0.75), 3),
        "p90_lb_per_month_per_device": round(_percentile(lb_series, 0.9), 3),
        "families_breakdown": families_breakdown,
        "lookback_days": lookback_days,
    }

    # Targeting: narrow to devices at or above the burn-rate percentile
    # floor. This is the pool signup_pct applies to; its conditional
    # mean (NOT the overall mean) drives per-subscriber economics.
    if target_percentile_floor > 0.0 and lb_series:
        threshold_lb = _percentile(lb_series, target_percentile_floor / 100.0)
        targeted = [d for d in eligible if d["lb_per_month"] >= threshold_lb]
    else:
        threshold_lb = 0.0
        targeted = list(eligible)

    targeted_lb_series = sorted(d["lb_per_month"] for d in targeted)
    targeted_families: dict[str, int] = {}
    for d in targeted:
        targeted_families[d["product_family"]] = targeted_families.get(d["product_family"], 0) + 1
    targeted_mean_lb_per_month = (
        sum(targeted_lb_series) / len(targeted_lb_series)
    ) if targeted_lb_series else 0.0
    targeted_stats = {
        "percentile_floor": round(target_percentile_floor, 1),
        "threshold_lb_per_month": round(threshold_lb, 3),
        "targeted_devices": len(targeted),
        "addressable_devices": len(eligible),
        "targeted_share_of_addressable_pct": round(
            100.0 * len(targeted) / len(eligible), 1
        ) if eligible else 0.0,
        "mean_lb_per_month_per_device": round(targeted_mean_lb_per_month, 3),
        "median_lb_per_month_per_device": round(_percentile(targeted_lb_series, 0.5), 3),
        "p25_lb_per_month_per_device": round(_percentile(targeted_lb_series, 0.25), 3),
        "p75_lb_per_month_per_device": round(_percentile(targeted_lb_series, 0.75), 3),
        "p90_lb_per_month_per_device": round(_percentile(targeted_lb_series, 0.9), 3),
        "families_breakdown": targeted_families,
        # How much richer is the targeted slice vs the whole cohort?
        # Useful gut-check for "does targeting heavy users actually move
        # the needle" — if this ratio is ~1.0, targeting is buying
        # nothing; if it's 2x+, it's the main economic lever.
        "lift_over_addressable_mean": (
            round(targeted_mean_lb_per_month / mean_lb_per_month, 2)
            if mean_lb_per_month > 0 else 1.0
        ),
    }

    # Projected signups + monthly / horizon projections with churn
    retail = float(sku.retail_price_usd or 0.0)
    margin_rate = margin_pct / 100.0
    churn_rate = monthly_churn_pct / 100.0

    # Signups + per-sub burn now derive from the TARGETED slice.
    initial_signups = len(targeted) * (signup_pct / 100.0)
    per_sub_monthly_lb = targeted_mean_lb_per_month
    per_sub_monthly_bags = (per_sub_monthly_lb / bag_size_lb) if bag_size_lb else 0.0
    per_sub_monthly_gmv = per_sub_monthly_bags * retail
    per_sub_monthly_margin = per_sub_monthly_gmv * margin_rate
    per_sub_monthly_jd_payout = per_sub_monthly_gmv - per_sub_monthly_margin

    month1_subs = initial_signups
    month1_lb = month1_subs * per_sub_monthly_lb
    month1_bags = month1_subs * per_sub_monthly_bags
    month1_gmv = month1_subs * per_sub_monthly_gmv
    month1_margin = month1_subs * per_sub_monthly_margin
    month1_jd_payout = month1_subs * per_sub_monthly_jd_payout

    curve: list[dict[str, Any]] = []
    cum_gmv = 0.0
    cum_margin = 0.0
    cum_jd = 0.0
    cum_lb = 0.0
    cum_bags = 0.0
    for m in range(1, horizon_months + 1):
        # Survivors at the start of this month under monthly churn.
        surviving = initial_signups * ((1.0 - churn_rate) ** (m - 1)) if churn_rate > 0 else initial_signups
        month_lb = surviving * per_sub_monthly_lb
        month_bags = surviving * per_sub_monthly_bags
        month_gmv = surviving * per_sub_monthly_gmv
        month_margin = surviving * per_sub_monthly_margin
        month_jd = surviving * per_sub_monthly_jd_payout
        cum_lb += month_lb
        cum_bags += month_bags
        cum_gmv += month_gmv
        cum_margin += month_margin
        cum_jd += month_jd
        curve.append({
            "month": m,
            "surviving_subscribers": round(surviving, 1),
            "lb": round(month_lb, 1),
            "bags": round(month_bags, 2),
            "gmv_usd": round(month_gmv, 2),
            "sg_margin_usd": round(month_margin, 2),
            "jd_payout_usd": round(month_jd, 2),
            "cumulative_gmv_usd": round(cum_gmv, 2),
            "cumulative_sg_margin_usd": round(cum_margin, 2),
            "cumulative_jd_payout_usd": round(cum_jd, 2),
        })

    ltv_per_sub = (cum_gmv / initial_signups) * margin_rate if initial_signups > 0 else 0.0

    return {
        "ok": True,
        "computed_at": now.isoformat(),
        "inputs": {
            "product_families": sorted(families_set) if families_set else None,
            "min_cooks_in_window": min_cooks_in_window,
            "lookback_days": lookback_days,
            "target_percentile_floor": round(target_percentile_floor, 1),
            "signup_pct": round(signup_pct, 2),
            "partner_product_id": sku.id,
            "margin_pct": round(margin_pct, 2),
            "monthly_churn_pct": round(monthly_churn_pct, 2),
            "horizon_months": horizon_months,
        },
        "sku": {
            "id": sku.id,
            "partner": sku.partner,
            "title": sku.title,
            "fuel_type": fuel_pref,
            "category": sku.category,
            "bag_size_lb": bag_size_lb,
            "retail_price_usd": round(retail, 2),
            "available": sku.available,
        },
        "cohort": cohort_stats,
        "targeted": targeted_stats,
        "projected_initial_signups": round(initial_signups, 1),
        "per_subscriber_monthly": {
            "lb": round(per_sub_monthly_lb, 3),
            "bags": round(per_sub_monthly_bags, 3),
            "gmv_usd": round(per_sub_monthly_gmv, 2),
            "sg_margin_usd": round(per_sub_monthly_margin, 2),
            "jd_payout_usd": round(per_sub_monthly_jd_payout, 2),
        },
        "month_1": {
            "subscribers": round(month1_subs, 1),
            "lb": round(month1_lb, 1),
            "bags": round(month1_bags, 2),
            "gmv_usd": round(month1_gmv, 2),
            "sg_margin_usd": round(month1_margin, 2),
            "jd_payout_usd": round(month1_jd_payout, 2),
        },
        "horizon_totals": {
            "months": horizon_months,
            "lb": round(cum_lb, 1),
            "bags": round(cum_bags, 2),
            "gmv_usd": round(cum_gmv, 2),
            "sg_margin_usd": round(cum_margin, 2),
            "jd_payout_usd": round(cum_jd, 2),
            "ltv_per_initial_subscriber_usd": round(ltv_per_sub, 2),
        },
        "monthly_curve": curve,
        "assumptions": {
            "shipping": "Jealous Devil absorbs shipping cost — excluded from Spider Grills margin",
            "burn_rate_source": "TelemetrySession × thermal model (lib/charcoalModel.ts Python twin)",
            "month_normalization_days": 30,
            "payment_processing_pct": 0,
            "refunds_pct": 0,
            "min_session_seconds": 300,
        },
    }


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
