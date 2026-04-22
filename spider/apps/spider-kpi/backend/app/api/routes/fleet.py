"""Fleet size + lifetime composition endpoints.

Replaces the hardcoded `13000` placeholder that was embedded in several
places (ProductEngineeringDivision hero, UniqueDeviceCohortPanel,
executive.probe_failure). The canonical definitions live here:

* **Active fleet** = unique devices that phoned home via telemetry in
  the last 24 months. Anything in ``TelemetrySession.device_id`` (real,
  not synthetic ``mac:xxx``) with ``session_start`` inside the window.
* **Lifetime fleet (AWS-registered)** = unique devices that have ever
  phoned home. Same source, no time window.
* **Product family** = from the latest-observed ``(grill_type,
  firmware_version)`` pair per device, run through
  ``classify_product`` — this is how the JOEHY factory-flash pattern
  (01.01.33 → Huntsman vs 01.01.34 → Weber Kettle) is resolved.

Results cache for 5 minutes in-memory (low-churn data, expensive
DISTINCT ON query). For cross-process persistence we'd promote this
to ``ai_narratives``-style persistence, but 5-minute staleness on a
fleet-size gauge is fine.
"""
from __future__ import annotations

import time as _time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_dashboard_session
from app.services.product_taxonomy import (
    ALL_FAMILIES,
    build_huntsman_device_ids,
    classify_product,
    classify_shopify_line_item,
)


router = APIRouter(
    prefix="/api/fleet",
    tags=["fleet"],
    dependencies=[Depends(require_dashboard_session)],
)


_CACHE_TTL_SECONDS = 300
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _cache_get(key: str) -> Optional[dict[str, Any]]:
    hit = _cache.get(key)
    if hit is None:
        return None
    ts, payload = hit
    if _time.time() - ts > _CACHE_TTL_SECONDS:
        _cache.pop(key, None)
        return None
    return payload


def _cache_put(key: str, payload: dict[str, Any]) -> None:
    _cache[key] = (_time.time(), payload)


def _bucket_by_family(
    rows: list[tuple[str, Optional[str], Optional[str]]],
    *,
    huntsman_device_ids: Optional[set[str]] = None,
) -> dict[str, int]:
    """rows is [(device_id, grill_type, firmware_version), ...] — one
    per device, latest-observed. Returns {family: count}.

    When ``huntsman_device_ids`` is supplied (the recommended path),
    classification uses per-device firmware history so JOEHY units that
    OTA'd past 01.01.33 still bucket into Huntsman rather than being
    misread as Weber Kettle from their current firmware alone.
    """
    counts: dict[str, int] = {f: 0 for f in ALL_FAMILIES}
    for device_id, grill_type, firmware in rows:
        family = classify_product(
            grill_type,
            firmware,
            device_id=device_id,
            huntsman_device_ids=huntsman_device_ids,
        )
        counts[family] = counts.get(family, 0) + 1
    return counts


def _distinct_device_latest(
    db: Session,
    *,
    since: Optional[datetime],
) -> list[tuple[str, Optional[str], Optional[str]]]:
    """For each distinct device_id in TelemetrySession, return the most
    recent (device_id, grill_type, firmware_version). Optionally bounded
    to sessions starting on/after ``since``.

    Synthetic ``mac:xxx`` device_ids are excluded — those are the
    alpha-bulk-import placeholders that haven't re-keyed to a real hash
    yet."""
    where_clauses = [
        "device_id IS NOT NULL",
        "device_id NOT LIKE 'mac:%%'",
    ]
    params: dict[str, Any] = {}
    if since is not None:
        where_clauses.append("session_start >= :since")
        params["since"] = since
    where_sql = " AND ".join(where_clauses)
    q = f"""
        SELECT DISTINCT ON (device_id)
            device_id, grill_type, firmware_version
        FROM telemetry_sessions
        WHERE {where_sql}
        ORDER BY device_id, session_start DESC NULLS LAST
    """
    return [(r[0], r[1], r[2]) for r in db.execute(text(q), params).all()]


@router.get("/size")
def fleet_size(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Canonical fleet-size number for the dashboard.

    Returns active_24mo (unique devices with telemetry in the last 24
    months), with a per-product-family breakdown. Every place that
    previously defaulted to ``13000`` should read from here.
    """
    cached = _cache_get("size")
    if cached is not None:
        return cached
    since = datetime.now(timezone.utc) - timedelta(days=365 * 2)
    rows = _distinct_device_latest(db, since=since)
    huntsman_ids = build_huntsman_device_ids(db)
    by_family = _bucket_by_family(rows, huntsman_device_ids=huntsman_ids)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": 730,
        "active_24mo": {
            "total": len(rows),
            "by_family": by_family,
        },
        "definition": (
            "Active fleet = unique devices that phoned home via "
            "telemetry in the last 24 months. Product family derived "
            "from each device's most-recent (grill_type, firmware_version) "
            "observation."
        ),
    }
    _cache_put("size", payload)
    return payload


@router.get("/lifetime")
def fleet_lifetime(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Lifetime fleet composition — three independent counters.

    * ``aws_registered`` — unique devices that have EVER phoned home.
      Authoritative for "how many units are out there provisioned."
    * ``shopify_units`` — unit count from Shopify line_items per product
      family. Populates once the connector has captured enough
      ``line_items`` history (the field was added 2026-04-21; historic
      order snapshots didn't include it, so this ramps up over time).
    * ``amazon_units`` — placeholder. Needs the Amazon SP-API Sales &
      Traffic Reports connector (not yet wired). Returns null with a
      reason so the UI can render "pending" gracefully.

    The three won't agree. Someone can buy a grill and never provision
    it (shopify_units would count them, aws_registered wouldn't). An
    original-owner sells to a new user who re-provisions under a new
    account — aws_registered counts both device_ids (they're separate
    Dynamo hashes). Keep the gap visible; don't try to reconcile.
    """
    cached = _cache_get("lifetime")
    if cached is not None:
        return cached
    rows_all_time = _distinct_device_latest(db, since=None)
    huntsman_ids = build_huntsman_device_ids(db)
    aws_by_family = _bucket_by_family(rows_all_time, huntsman_device_ids=huntsman_ids)

    # Shopify line_items — extended on the connector 2026-04-21, so most
    # historic snapshots don't yet have them. Count what we have and
    # surface the coverage separately so the number isn't misread.
    shopify_row = db.execute(text("""
        WITH li AS (
            SELECT jsonb_array_elements(raw_payload->'line_items') AS line
            FROM shopify_order_events
            WHERE event_type = 'poll.order_snapshot'
              AND jsonb_typeof(raw_payload->'line_items') = 'array'
        )
        SELECT
            lower(coalesce(line->>'title', '')) AS title,
            COALESCE((line->>'quantity')::int, 0) AS qty
        FROM li
    """)).all()

    shopify_by_family: dict[str, int] = {f: 0 for f in ALL_FAMILIES}
    shopify_total = 0
    for title, qty in shopify_row:
        # Shared classifier — honours CONSOLIDATE_GIANT_HUNTSMAN so this
        # lines up with the AWS-telemetry counter rather than forking
        # into its own bucketing.
        fam = classify_shopify_line_item(title or "")
        shopify_by_family[fam] = shopify_by_family.get(fam, 0) + qty
        shopify_total += qty

    orders_with_line_items = db.execute(text("""
        SELECT count(*) FROM shopify_order_events
        WHERE event_type = 'poll.order_snapshot'
          AND jsonb_typeof(raw_payload->'line_items') = 'array'
    """)).scalar() or 0
    orders_total = db.execute(text("""
        SELECT count(*) FROM shopify_order_events
        WHERE event_type = 'poll.order_snapshot'
    """)).scalar() or 0

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "aws_registered": {
            "total": len(rows_all_time),
            "by_family": aws_by_family,
            "note": "Every device that has ever phoned home. Authoritative for provisioned units.",
        },
        "shopify_units": {
            "total": shopify_total,
            "by_family": shopify_by_family,
            "coverage_orders_with_line_items": int(orders_with_line_items),
            "coverage_orders_total": int(orders_total),
            "note": (
                "Unit-level Shopify sales by product family. `line_items` "
                "capture was added to the connector on 2026-04-21; orders "
                "synced before that date do not carry line-item data, so "
                "this number ramps up as new orders flow through. "
                "`coverage_orders_with_line_items / coverage_orders_total` "
                "shows how much of the historical order set is covered so "
                "far."
            ),
        },
        "amazon_units": {
            "total": None,
            "by_family": None,
            "note": (
                "Pending — requires the Amazon SP-API Sales & Traffic "
                "Reports connector. Amazon catalog listings are already "
                "synced, but unit-level sales aren't pulled yet."
            ),
        },
    }
    _cache_put("lifetime", payload)
    return payload
