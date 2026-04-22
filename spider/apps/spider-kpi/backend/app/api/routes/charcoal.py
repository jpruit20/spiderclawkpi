"""Charcoal usage analytics — data source for the per-device / fleet /
JIT sub-page under Product Engineering.

The thermal model itself lives in the frontend (TypeScript,
``lib/charcoalModel.ts``) so its parameters can be tuned in the browser
without a backend round-trip. This module's job is to serve the
*cook-session records* the model runs over:

  * per-device history (MAC → session list)
  * fleet-wide aggregation by date range + cohort filters

No storage added — everything is derived from ``TelemetrySession`` and
``TelemetryStreamEvent`` using the existing MAC-resolution path
(``firmware.normalize_mac`` + ``_device_ids_for_mac``).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_dashboard_session
from app.models import CharcoalJITSubscription, PartnerProduct, TelemetrySession
from app.services.product_taxonomy import (
    FAMILY_HUNTSMAN,
    FAMILY_WEBER_KETTLE,
    classify_product,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/charcoal",
    tags=["charcoal"],
    dependencies=[Depends(require_dashboard_session)],
)


# Lower bound on cook duration before we count it as a "real" cook.
# Short events (< ~5 min) are typically a test-fire or a command glitch
# — including them inflates session counts and depresses the avg-temp
# computation because many such events never left ambient.
MIN_SESSION_SECONDS = 5 * 60


def _avg_from_series(series: Any) -> Optional[float]:
    """TelemetrySession.actual_temp_time_series is a JSONB list of
    ``{t, v}`` samples. Return the arithmetic mean of ``v`` values,
    or None if the series is empty / unparseable."""
    if not series or not isinstance(series, list):
        return None
    vals: list[float] = []
    for s in series:
        try:
            v = float(s.get("v"))
        except (AttributeError, TypeError, ValueError):
            continue
        if v > 0 and v < 1000:  # filter probe-not-connected spikes
            vals.append(v)
    if not vals:
        return None
    return sum(vals) / len(vals)


def _summarize_session(s: TelemetrySession) -> dict[str, Any]:
    """Compact per-session payload the charcoal model consumes."""
    avg_actual = _avg_from_series(s.actual_temp_time_series)
    hours = (s.session_duration_seconds or 0) / 3600.0
    return {
        "session_id": s.session_id,
        "source_event_id": s.source_event_id,
        "device_id": s.device_id,
        "session_start": s.session_start.isoformat() if s.session_start else None,
        "session_end": s.session_end.isoformat() if s.session_end else None,
        "duration_hours": round(hours, 3),
        "target_temp_f": s.target_temp,
        "avg_actual_temp_f": round(avg_actual, 1) if avg_actual is not None else None,
        "grill_type": s.grill_type,
        "firmware_version": s.firmware_version,
        "cook_success": bool(s.cook_success),
        "product_family": classify_product(s.grill_type, s.firmware_version),
    }


@router.get("/device/{mac}/sessions")
def device_sessions(
    mac: str,
    days: int = 730,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """All cook sessions for a single device, newest first.

    ``mac`` accepts any common format (colons, dashes, no separators).
    Sessions below MIN_SESSION_SECONDS are filtered out. The caller
    (frontend charcoal model) computes fuel consumption per session.
    """
    from app.api.routes.firmware import _device_ids_for_mac, normalize_mac

    normalized = normalize_mac(mac)
    if normalized is None:
        raise HTTPException(status_code=400, detail="invalid MAC")

    device_ids = _device_ids_for_mac(db, normalized)
    if not device_ids:
        return {
            "mac": normalized,
            "device_id_count": 0,
            "sessions": [],
            "note": "No telemetry_stream_events for this MAC — device may be offline or never provisioned.",
        }

    days = max(1, min(days, 365 * 3))
    window_start = datetime.now(timezone.utc) - timedelta(days=days)

    rows = db.execute(
        select(TelemetrySession)
        .where(TelemetrySession.device_id.in_(device_ids))
        .where(TelemetrySession.session_start >= window_start)
        .where(TelemetrySession.session_duration_seconds >= MIN_SESSION_SECONDS)
        .order_by(TelemetrySession.session_start.desc())
    ).scalars().all()

    return {
        "mac": normalized,
        "device_id_count": len(device_ids),
        "window_days": days,
        "sessions": [_summarize_session(s) for s in rows],
    }


@router.get("/fleet/aggregate")
def fleet_aggregate(
    start: Optional[str] = None,
    end: Optional[str] = None,
    grill_type: Optional[str] = None,
    firmware_version: Optional[str] = None,
    product_family: Optional[str] = None,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Fleet-wide charcoal-relevant aggregation.

    Returns totals + one row per device with cook hours + avg temp so
    the frontend can (a) render per-device burn-rate distribution and
    (b) run the thermal model against each device's average cook
    profile.

    Filters:
      * ``start`` / ``end`` — ISO date strings; default last 180 days.
      * ``grill_type`` / ``firmware_version`` — exact match.
      * ``product_family`` — applies the classifier (Weber Kettle /
        Huntsman / Giant Huntsman / Unknown).

    A full session dump would be huge — this endpoint aggregates in
    SQL and ships only per-device row counts + summaries.
    """
    now = datetime.now(timezone.utc)
    try:
        end_dt = datetime.fromisoformat(end) if end else now
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid `end` date")
    try:
        start_dt = datetime.fromisoformat(start) if start else (end_dt - timedelta(days=180))
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid `start` date")
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    if start_dt >= end_dt:
        raise HTTPException(status_code=400, detail="`start` must be before `end`")

    # We want avg actual temp, total hours, and last firmware seen per
    # device. Two queries: first a grouped aggregate on TelemetrySession
    # (cheap — sessions are small), then a lookup for latest fw per
    # device via DISTINCT ON.
    where_clauses = [
        "device_id IS NOT NULL",
        "device_id NOT LIKE 'mac:%%'",
        "session_start >= :start_dt",
        "session_start < :end_dt",
        "session_duration_seconds >= :min_seconds",
    ]
    params: dict[str, Any] = {
        "start_dt": start_dt,
        "end_dt": end_dt,
        "min_seconds": MIN_SESSION_SECONDS,
    }
    if grill_type:
        where_clauses.append("grill_type = :grill_type")
        params["grill_type"] = grill_type
    if firmware_version:
        where_clauses.append("firmware_version = :firmware_version")
        params["firmware_version"] = firmware_version

    where_sql = " AND ".join(where_clauses)
    per_device_rows = db.execute(text(f"""
        SELECT
            device_id,
            count(*) AS sessions,
            sum(session_duration_seconds)::float / 3600.0 AS cook_hours,
            avg(target_temp) AS avg_target_temp,
            -- Average actual-temp requires pulling the time-series.
            -- We compute a proxy here from the DB-level fields we have
            -- and let the frontend refine per-session where needed.
            avg(CASE WHEN target_temp IS NOT NULL THEN target_temp ELSE 0 END) AS avg_temp_proxy,
            max(session_start) AS last_session_at,
            min(session_start) AS first_session_at
        FROM telemetry_sessions
        WHERE {where_sql}
        GROUP BY device_id
        ORDER BY cook_hours DESC
    """), params).all()

    # Latest firmware / grill_type per device in the window.
    latest_meta = {r[0]: (r[1], r[2]) for r in db.execute(text(f"""
        SELECT DISTINCT ON (device_id)
            device_id, grill_type, firmware_version
        FROM telemetry_sessions
        WHERE {where_sql}
        ORDER BY device_id, session_start DESC
    """), params).all()}

    per_device: list[dict[str, Any]] = []
    for r in per_device_rows:
        device_id, sessions, cook_hours, avg_target, avg_temp_proxy, last_seen, first_seen = r
        meta_grill, meta_fw = latest_meta.get(device_id, (None, None))
        family = classify_product(meta_grill, meta_fw)
        if product_family and family != product_family:
            continue
        per_device.append({
            "device_id": device_id,
            "sessions": int(sessions or 0),
            "cook_hours": round(float(cook_hours or 0.0), 2),
            "avg_target_temp_f": round(float(avg_target), 1) if avg_target is not None else None,
            "avg_cook_temp_f": round(float(avg_temp_proxy), 1) if avg_temp_proxy else None,
            "grill_type": meta_grill,
            "firmware_version": meta_fw,
            "product_family": family,
            "first_session_at": first_seen.isoformat() if first_seen else None,
            "last_session_at": last_seen.isoformat() if last_seen else None,
        })

    # Fleet totals (post-filter).
    total_cook_hours = sum(d["cook_hours"] for d in per_device)
    total_sessions = sum(d["sessions"] for d in per_device)

    # Family rollup for quick readout
    by_family: dict[str, dict[str, Any]] = {}
    for d in per_device:
        fam = d["product_family"]
        b = by_family.setdefault(fam, {"devices": 0, "sessions": 0, "cook_hours": 0.0})
        b["devices"] += 1
        b["sessions"] += d["sessions"]
        b["cook_hours"] += d["cook_hours"]
    by_family_out = [
        {"product_family": fam, **vals, "cook_hours": round(vals["cook_hours"], 1)}
        for fam, vals in sorted(by_family.items(), key=lambda kv: -kv[1]["cook_hours"])
    ]

    return {
        "window": {
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "days": (end_dt - start_dt).days,
        },
        "filters": {
            "grill_type": grill_type,
            "firmware_version": firmware_version,
            "product_family": product_family,
        },
        "fleet_totals": {
            "unique_devices": len(per_device),
            "total_sessions": total_sessions,
            "total_cook_hours": round(total_cook_hours, 1),
        },
        "by_family": by_family_out,
        "per_device": per_device,
    }


@router.get("/fleet/distinct-filters")
def fleet_distinct_filters(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Populate the Fleet tab's filter dropdowns — distinct grill_types
    and firmware_versions seen in the last 24 months."""
    window_start = datetime.now(timezone.utc) - timedelta(days=730)
    grills = db.execute(
        select(TelemetrySession.grill_type, func.count(func.distinct(TelemetrySession.device_id)))
        .where(TelemetrySession.session_start >= window_start)
        .where(TelemetrySession.grill_type.is_not(None))
        .group_by(TelemetrySession.grill_type)
        .order_by(func.count(func.distinct(TelemetrySession.device_id)).desc())
    ).all()
    firmwares = db.execute(
        select(TelemetrySession.firmware_version, func.count(func.distinct(TelemetrySession.device_id)))
        .where(TelemetrySession.session_start >= window_start)
        .where(TelemetrySession.firmware_version.is_not(None))
        .group_by(TelemetrySession.firmware_version)
        .order_by(func.count(func.distinct(TelemetrySession.device_id)).desc())
    ).all()
    return {
        "grill_types": [{"value": g or "Unknown", "devices": int(n)} for g, n in grills],
        "firmware_versions": [{"value": f, "devices": int(n)} for f, n in firmwares],
        "product_families": [FAMILY_WEBER_KETTLE, FAMILY_HUNTSMAN, "Giant Huntsman", "Unknown"],
    }


# ── JIT program enrollment ──────────────────────────────────────────
#
# Backs the "Enrollment" tab on the Charcoal page. One row per
# (device, user) pair. The scheduler (to be added) will read this
# table, compute burn rate per device from TelemetrySession, and
# write `next_ship_after` timestamps. Draft Shopify order creation
# is explicitly NOT wired here yet — we're collecting enrollments
# first so we can run the prediction cadence dry before any
# shipments are billed.


VALID_FUELS = ("lump", "briquette")
VALID_STATUSES = ("active", "paused", "cancelled")


class JITSubscribeIn(BaseModel):
    mac: str = Field(..., max_length=32)
    user_key: Optional[str] = Field(None, max_length=128)
    fuel_preference: str = Field(..., description="'lump' or 'briquette'")
    bag_size_lb: int = Field(20, ge=5, le=100)
    lead_time_days: int = Field(5, ge=1, le=30)
    safety_stock_days: int = Field(7, ge=0, le=30)
    shipping_zip: Optional[str] = Field(None, max_length=16)
    shipping_lat: Optional[float] = None
    shipping_lon: Optional[float] = None
    notes: Optional[str] = None
    partner_product_id: Optional[int] = Field(
        None, description="FK to partner_products — when set, retail price + bag size flow from the partner catalog.",
    )
    margin_pct: float = Field(10.0, ge=0, le=100, description="Spider Grills' cut on each shipment.")


class JITPatchIn(BaseModel):
    fuel_preference: Optional[str] = None
    bag_size_lb: Optional[int] = Field(None, ge=5, le=100)
    lead_time_days: Optional[int] = Field(None, ge=1, le=30)
    safety_stock_days: Optional[int] = Field(None, ge=0, le=30)
    shipping_zip: Optional[str] = None
    shipping_lat: Optional[float] = None
    shipping_lon: Optional[float] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    partner_product_id: Optional[int] = None
    margin_pct: Optional[float] = Field(None, ge=0, le=100)


def _serialize_product(p: PartnerProduct) -> dict[str, Any]:
    return {
        "id": p.id,
        "partner": p.partner,
        "handle": p.handle,
        "title": p.title,
        "fuel_type": p.fuel_type,
        "bag_size_lb": p.bag_size_lb,
        "retail_price_usd": p.retail_price_usd,
        "currency": p.currency,
        "source_url": p.source_url,
        "available": p.available,
        "last_fetched_at": p.last_fetched_at.isoformat() if p.last_fetched_at else None,
    }


def _serialize_sub(row: CharcoalJITSubscription) -> dict[str, Any]:
    return {
        "id": row.id,
        "device_id": row.device_id,
        "mac": row.mac_normalized,
        "user_key": row.user_key,
        "fuel_preference": row.fuel_preference,
        "bag_size_lb": row.bag_size_lb,
        "lead_time_days": row.lead_time_days,
        "safety_stock_days": row.safety_stock_days,
        "shipping_zip": row.shipping_zip,
        "shipping_lat": row.shipping_lat,
        "shipping_lon": row.shipping_lon,
        "status": row.status,
        "enrolled_by": row.enrolled_by,
        "notes": row.notes,
        "partner_product_id": row.partner_product_id,
        "margin_pct": row.margin_pct,
        "last_forecast": row.last_forecast_json or {},
        "last_shipped_at": row.last_shipped_at.isoformat() if row.last_shipped_at else None,
        "next_ship_after": row.next_ship_after.isoformat() if row.next_ship_after else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.post("/jit/subscribe")
def jit_subscribe(
    payload: JITSubscribeIn,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Enroll a device in the Charcoal JIT program.

    Resolves the MAC to a device_id via the existing telemetry-stream
    lookup. If no device_ids exist (offline device), we store the
    subscription with device_id=NULL; the scheduler will re-key it
    when telemetry first arrives.
    """
    from app.api.routes.firmware import _device_ids_for_mac, normalize_mac

    if payload.fuel_preference not in VALID_FUELS:
        raise HTTPException(status_code=400, detail=f"fuel_preference must be one of {VALID_FUELS}")

    mac = normalize_mac(payload.mac)
    if mac is None:
        raise HTTPException(status_code=400, detail="invalid MAC")

    device_ids = _device_ids_for_mac(db, mac)
    # Prefer the most-recently-seen device_id when a MAC maps to several.
    primary_device_id = device_ids[0] if device_ids else None

    existing = db.execute(
        select(CharcoalJITSubscription).where(
            CharcoalJITSubscription.mac_normalized == mac,
            (CharcoalJITSubscription.user_key == payload.user_key),
        )
    ).scalars().first()

    if existing is not None:
        # Idempotent upsert — update fields, preserve subscription ID.
        existing.device_id = primary_device_id or existing.device_id
        existing.fuel_preference = payload.fuel_preference
        existing.bag_size_lb = payload.bag_size_lb
        existing.lead_time_days = payload.lead_time_days
        existing.safety_stock_days = payload.safety_stock_days
        if payload.shipping_zip is not None:
            existing.shipping_zip = payload.shipping_zip
        if payload.shipping_lat is not None:
            existing.shipping_lat = payload.shipping_lat
        if payload.shipping_lon is not None:
            existing.shipping_lon = payload.shipping_lon
        if payload.notes is not None:
            existing.notes = payload.notes
        if payload.partner_product_id is not None:
            existing.partner_product_id = payload.partner_product_id
        existing.margin_pct = float(payload.margin_pct)
        existing.status = "active"
        # Re-forecast so the updated product/margin is reflected
        try:
            from app.services.charcoal_jit import forecast_subscription
            forecast_subscription(db, existing)
        except Exception:
            logger.exception("re-forecast on update failed")
        db.commit()
        return {"ok": True, "action": "updated", "subscription": _serialize_sub(existing)}

    # Auto-fill shipping address from most recent Shopify order if the
    # user supplied a user_key (expected to be email) but no zip.
    ship_zip = payload.shipping_zip
    ship_lat = payload.shipping_lat
    ship_lon = payload.shipping_lon
    if not ship_zip and payload.user_key:
        from app.services.charcoal_jit import lookup_shipping_address
        addr = lookup_shipping_address(db, user_key=payload.user_key)
        if addr:
            if addr.get("zip"): ship_zip = str(addr["zip"])
            if addr.get("latitude") is not None:
                try: ship_lat = float(addr["latitude"])
                except (TypeError, ValueError): pass
            if addr.get("longitude") is not None:
                try: ship_lon = float(addr["longitude"])
                except (TypeError, ValueError): pass

    row = CharcoalJITSubscription(
        device_id=primary_device_id,
        mac_normalized=mac,
        user_key=payload.user_key,
        fuel_preference=payload.fuel_preference,
        bag_size_lb=payload.bag_size_lb,
        lead_time_days=payload.lead_time_days,
        safety_stock_days=payload.safety_stock_days,
        shipping_zip=ship_zip,
        shipping_lat=ship_lat,
        shipping_lon=ship_lon,
        notes=payload.notes,
        partner_product_id=payload.partner_product_id,
        margin_pct=float(payload.margin_pct),
        status="active",
        enrolled_by="dashboard",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    # Compute an initial forecast so the row doesn't show empty.
    try:
        from app.services.charcoal_jit import forecast_subscription
        forecast_subscription(db, row)
        db.commit()
        db.refresh(row)
    except Exception:
        logger.exception("initial forecast on enrollment failed; subscription created regardless")
        db.rollback()

    return {"ok": True, "action": "created", "subscription": _serialize_sub(row)}


@router.get("/jit/subscriptions")
def jit_list(
    status: Optional[str] = None,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """All JIT subscriptions, optionally filtered by status."""
    stmt = select(CharcoalJITSubscription).order_by(desc(CharcoalJITSubscription.updated_at))
    if status:
        if status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"status must be one of {VALID_STATUSES}")
        stmt = stmt.where(CharcoalJITSubscription.status == status)
    rows = db.execute(stmt).scalars().all()
    by_status: dict[str, int] = {}
    by_fuel: dict[str, int] = {}
    for r in rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        by_fuel[r.fuel_preference] = by_fuel.get(r.fuel_preference, 0) + 1
    return {
        "subscriptions": [_serialize_sub(r) for r in rows],
        "count": len(rows),
        "by_status": by_status,
        "by_fuel": by_fuel,
    }


@router.patch("/jit/subscriptions/{subscription_id}")
def jit_patch(
    subscription_id: int,
    payload: JITPatchIn,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Update a subscription — pause, cancel, change bag size, etc."""
    row = db.get(CharcoalJITSubscription, subscription_id)
    if row is None:
        raise HTTPException(status_code=404, detail="subscription not found")
    if payload.fuel_preference is not None:
        if payload.fuel_preference not in VALID_FUELS:
            raise HTTPException(status_code=400, detail=f"fuel_preference must be one of {VALID_FUELS}")
        row.fuel_preference = payload.fuel_preference
    if payload.bag_size_lb is not None: row.bag_size_lb = payload.bag_size_lb
    if payload.lead_time_days is not None: row.lead_time_days = payload.lead_time_days
    if payload.safety_stock_days is not None: row.safety_stock_days = payload.safety_stock_days
    if payload.shipping_zip is not None: row.shipping_zip = payload.shipping_zip
    if payload.shipping_lat is not None: row.shipping_lat = payload.shipping_lat
    if payload.shipping_lon is not None: row.shipping_lon = payload.shipping_lon
    if payload.notes is not None: row.notes = payload.notes
    if payload.status is not None:
        if payload.status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"status must be one of {VALID_STATUSES}")
        row.status = payload.status
    if payload.partner_product_id is not None: row.partner_product_id = payload.partner_product_id
    if payload.margin_pct is not None: row.margin_pct = float(payload.margin_pct)
    # Re-forecast when anything pricing-related changed so the UI
    # reflects the new financial model immediately.
    if any(v is not None for v in (
        payload.partner_product_id, payload.margin_pct, payload.bag_size_lb,
        payload.lead_time_days, payload.safety_stock_days, payload.fuel_preference,
    )):
        try:
            from app.services.charcoal_jit import forecast_subscription
            forecast_subscription(db, row)
        except Exception:
            logger.exception("re-forecast on patch failed")
    db.commit()
    db.refresh(row)
    return {"ok": True, "subscription": _serialize_sub(row)}


@router.post("/jit/subscriptions/{subscription_id}/forecast")
def jit_forecast_now(
    subscription_id: int,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Manually re-compute the forecast for one subscription. Same math
    the scheduler runs daily — useful when Joseph wants to see the
    impact of a parameter change immediately without waiting."""
    from app.services.charcoal_jit import forecast_subscription
    row = db.get(CharcoalJITSubscription, subscription_id)
    if row is None:
        raise HTTPException(status_code=404, detail="subscription not found")
    result = forecast_subscription(db, row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "forecast": result, "subscription": _serialize_sub(row)}


@router.post("/jit/forecast-all")
def jit_forecast_all(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Run the forecast pass across every non-cancelled subscription
    on demand. Backs a "Run forecast now" button on the enrollment
    tab so Joseph doesn't have to wait 24h to see predictions update."""
    from app.services.charcoal_jit import run_daily_forecast_pass
    return run_daily_forecast_pass(db)


# ── Partner product catalog ──────────────────────────────────────────


@router.get("/partners/products")
def partners_list_products(
    partner: Optional[str] = None,
    available_only: bool = True,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """List upstream partner products that the JIT program can
    fulfill against. Populates the enrollment form's product dropdown
    and backs the financial modeling tab.
    """
    stmt = select(PartnerProduct).order_by(
        PartnerProduct.partner.asc(), PartnerProduct.bag_size_lb.desc().nullslast(),
    )
    if partner:
        stmt = stmt.where(PartnerProduct.partner == partner)
    if available_only:
        stmt = stmt.where(PartnerProduct.available.is_(True))
    rows = db.execute(stmt).scalars().all()
    return {
        "products": [_serialize_product(p) for p in rows],
        "count": len(rows),
    }


@router.post("/partners/refresh")
def partners_refresh(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Manually refresh every partner's catalog. Same work the daily
    scheduler runs — useful when Joseph wants to see today's prices
    without waiting for the cron."""
    from app.services.partner_catalog import refresh_all_partners
    return refresh_all_partners(db)


@router.delete("/jit/subscriptions/{subscription_id}")
def jit_cancel(
    subscription_id: int,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Soft-cancel: flip status to 'cancelled' rather than delete, so
    we retain audit trail. Use the PATCH endpoint with status=active
    to re-enroll."""
    row = db.get(CharcoalJITSubscription, subscription_id)
    if row is None:
        raise HTTPException(status_code=404, detail="subscription not found")
    row.status = "cancelled"
    db.commit()
    return {"ok": True, "subscription": _serialize_sub(row)}
