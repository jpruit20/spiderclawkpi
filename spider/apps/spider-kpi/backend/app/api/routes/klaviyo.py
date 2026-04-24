"""Dashboard-side Klaviyo query API.

Klaviyo is the intermediary between Agustin's native grill app and
the dashboard (see ``ingestion/connectors/klaviyo.py`` docstring).
This router exposes aggregated views over the mirrored
``klaviyo_profiles`` and ``klaviyo_events`` tables so UI cards can
render without going back to Klaviyo on every request.

Endpoints:

* ``/api/klaviyo/app-engagement`` — DAU/MAU + daily unique-profile
  timeseries for the "Opened App" metric. Used by the Product
  Engineering "App & Users" card.

* ``/api/klaviyo/app-profile-summary`` — phone platform mix (iOS vs
  Android), app version distribution, device-type tallies from the
  Klaviyo profile properties array. Gives the mobile fleet
  composition distinct from the Venom controller telemetry.

* ``/api/klaviyo/customer-lookup`` — single-email lookup: profile
  properties + recent events. Used by CX for triage — "this ticket
  requester opened the app 12 min ago on Android 14, owns a Huntsman,
  firmware 01.01.33, expected next charcoal order 06/15".

* ``/api/klaviyo/product-ownership-breakdown`` — distribution of the
  ``Product Ownership`` label across active profiles. Powers the
  Huntsman / Kettle / Giant Huntsman reconciliation against the
  telemetry-side classification.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.models import KlaviyoEvent, KlaviyoProfile


router = APIRouter(prefix="/api/klaviyo", tags=["klaviyo"])


@router.get("/app-engagement")
def app_engagement(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Daily & 30-day unique-profile counts for ``Opened App``.

    ``dau`` = unique profiles with Opened App events in the last 24h.
    ``mau`` = same over the last 30 days. The rolling series is the
    *daily unique opener* count, which is what charts should render
    rather than event counts (power users can open the app dozens of
    times a day).
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    # Daily unique-profile series — SQL is cheaper than pulling the
    # raw firehose into Python.
    rows = db.execute(text("""
        SELECT
            (event_datetime AT TIME ZONE 'America/New_York')::date AS business_date,
            COUNT(DISTINCT klaviyo_profile_id) AS unique_profiles,
            COUNT(*) AS events
        FROM klaviyo_events
        WHERE metric_name = 'Opened App'
          AND event_datetime >= :since
          AND klaviyo_profile_id IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """), {"since": since}).all()

    series = [
        {
            "date": r.business_date.isoformat(),
            "unique_profiles": int(r.unique_profiles or 0),
            "events": int(r.events or 0),
        }
        for r in rows
    ]

    dau = db.execute(text("""
        SELECT COUNT(DISTINCT klaviyo_profile_id)
        FROM klaviyo_events
        WHERE metric_name = 'Opened App'
          AND event_datetime >= :cutoff
    """), {"cutoff": now - timedelta(days=1)}).scalar() or 0

    mau = db.execute(text("""
        SELECT COUNT(DISTINCT klaviyo_profile_id)
        FROM klaviyo_events
        WHERE metric_name = 'Opened App'
          AND event_datetime >= :cutoff
    """), {"cutoff": now - timedelta(days=30)}).scalar() or 0

    latest_event = db.execute(text(
        "SELECT MAX(event_datetime) FROM klaviyo_events WHERE metric_name = 'Opened App'"
    )).scalar()

    return {
        "generated_at": now.isoformat(),
        "window_days": days,
        "dau": int(dau),
        "mau": int(mau),
        "stickiness_pct": round((int(dau) / int(mau) * 100.0) if mau else 0.0, 1),
        "latest_event_at": latest_event.isoformat() if latest_event else None,
        "daily_unique_openers": series,
    }


@router.get("/app-profile-summary")
def app_profile_summary(
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Phone platform mix + app version distribution + device types.

    Restricted to profiles that have ever reported at least one of:
    ``phone_os``, ``app_version``, or ``device_types`` (i.e. profiles
    who actually installed and opened the app — not every Shopify-synced
    profile).
    """
    # One query over profile rows that have ANY app signal.
    profiles = db.execute(
        select(
            KlaviyoProfile.phone_os,
            KlaviyoProfile.phone_brand,
            KlaviyoProfile.app_version,
            KlaviyoProfile.device_types,
            KlaviyoProfile.last_event_at,
        ).where(
            (KlaviyoProfile.phone_os.isnot(None))
            | (KlaviyoProfile.app_version.isnot(None))
            | (func.array_length(KlaviyoProfile.device_types, 1).isnot(None))
        )
    ).all()

    phone_os: Counter = Counter()
    phone_brand: Counter = Counter()
    app_version: Counter = Counter()
    device_types: Counter = Counter()
    active_30d = 0
    cutoff_30d = datetime.now(timezone.utc) - timedelta(days=30)

    for row in profiles:
        if row.phone_os:
            phone_os[row.phone_os] += 1
        if row.phone_brand:
            phone_brand[row.phone_brand] += 1
        if row.app_version:
            app_version[row.app_version] += 1
        for dt in row.device_types or []:
            device_types[dt] += 1
        if row.last_event_at and row.last_event_at >= cutoff_30d:
            active_30d += 1

    def top(counter: Counter, n: int = 10) -> list[dict[str, Any]]:
        total = sum(counter.values()) or 1
        return [
            {"label": k, "count": v, "pct": round(v / total * 100.0, 1)}
            for k, v in counter.most_common(n)
        ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "app_profiles": len(profiles),
        "active_30d": active_30d,
        "phone_os": top(phone_os),
        "phone_brand": top(phone_brand),
        "app_version": top(app_version),
        "device_types": top(device_types),
    }


@router.get("/product-ownership-breakdown")
def product_ownership_breakdown(
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Distribution of grill ownership derived from Klaviyo.

    Two independent signals are reported so they can be reconciled:

    * **tagged_ownership** — the Klaviyo ``Product Ownership`` label
      that Klaviyo itself maintains (e.g. "Huntsman Owners"). Coarse,
      doesn't split Giant Huntsman.

    * **from_orders** — derived from ``Placed Order`` event line-items
      (which mirror Shopify), so ``Giant Huntsman™`` and
      ``HUNTSMAN - PRE ORDER`` variants get counted separately. This
      is what the dashboard should trust when splitting Huntsman vs
      Giant Huntsman, because AWS-side telemetry can't tell them apart.
    """
    tagged_rows = db.execute(
        select(
            KlaviyoProfile.product_ownership,
            func.count().label("n"),
        )
        .where(KlaviyoProfile.product_ownership.isnot(None))
        .group_by(KlaviyoProfile.product_ownership)
        .order_by(func.count().desc())
    ).all()
    tagged_total = sum(int(r.n) for r in tagged_rows) or 1

    # Derive per-family ownership from Placed Order event line-items.
    # Each event's ``properties.Items`` is a list of product titles that
    # match verbatim against Shopify product names. We count DISTINCT
    # profiles (not orders) because one customer can have multiple
    # orders of the same family.
    # Product-title matchers (lowercased). Order matters: Giant
    # Huntsman must be checked BEFORE Huntsman so the substring
    # "huntsman" doesn't eat the giant-huntsman signal first.
    family_rules = [
        ("Giant Huntsman", ["giant huntsman"]),
        ("Huntsman", ["the huntsman", "huntsman - pre order", " huntsman "]),
        ("Kettle (Venom)", ["venom"]),
        ("Webcraft", ["webcraft"]),
    ]

    # Pull the set of (profile_id, items_text) pairs for Placed Order
    # events. Cast jsonb → text once so we can substring-match cheaply.
    rows = db.execute(text("""
        SELECT DISTINCT
            klaviyo_profile_id,
            LOWER(COALESCE(properties->>'Items', properties::text)) AS items_blob
        FROM klaviyo_events
        WHERE metric_name = 'Placed Order'
          AND klaviyo_profile_id IS NOT NULL
    """)).all()

    per_family: dict[str, set[str]] = {name: set() for name, _ in family_rules}
    for pid, blob in rows:
        if not blob:
            continue
        for name, needles in family_rules:
            if any(n in blob for n in needles):
                per_family[name].add(pid)
                # A profile that bought Giant Huntsman is NOT also
                # bucketed under plain Huntsman — we want crisp counts.
                if name == "Giant Huntsman":
                    break

    from_orders = [
        {"family": name, "unique_profiles": len(per_family[name])}
        for name, _ in family_rules
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tagged_ownership": {
            "total_profiles": tagged_total,
            "breakdown": [
                {"ownership": r.product_ownership, "count": int(r.n), "pct": round(int(r.n) / tagged_total * 100.0, 1)}
                for r in tagged_rows
            ],
        },
        "from_orders": from_orders,
    }


@router.get("/customer-lookup")
def customer_lookup(
    email: Optional[str] = Query(default=None, description="Email to look up"),
    external_id: Optional[str] = Query(default=None, description="Klaviyo externalId (sg-app-NNNNN)"),
    limit_events: int = Query(25, ge=1, le=200),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Pull a profile + recent events for a CX ticket requester.

    Either ``email`` or ``external_id`` is required. Returns the
    profile's app/device state plus the most recent N events so the
    support agent can see "opened app 12 min ago, last cook yesterday,
    owns Huntsman on 01.01.33".
    """
    if not email and not external_id:
        return {"error": "provide email or external_id"}

    q = select(KlaviyoProfile)
    if email:
        q = q.where(KlaviyoProfile.email == email.lower())
    else:
        q = q.where(KlaviyoProfile.external_id == external_id)
    profile = db.execute(q.limit(1)).scalar_one_or_none()
    if profile is None:
        return {
            "found": False,
            "email": email,
            "external_id": external_id,
        }

    events = db.execute(
        select(
            KlaviyoEvent.metric_name,
            KlaviyoEvent.event_datetime,
            KlaviyoEvent.properties,
        )
        .where(KlaviyoEvent.klaviyo_profile_id == profile.klaviyo_id)
        .order_by(KlaviyoEvent.event_datetime.desc())
        .limit(limit_events)
    ).all()

    return {
        "found": True,
        "profile": {
            "klaviyo_id": profile.klaviyo_id,
            "external_id": profile.external_id,
            "email": profile.email,
            "first_name": profile.first_name,
            "last_name": profile.last_name,
            "device_types": profile.device_types,
            "device_firmware_versions": profile.device_firmware_versions,
            "product_ownership": profile.product_ownership,
            "phone_os": profile.phone_os,
            "phone_model": profile.phone_model,
            "phone_os_version": profile.phone_os_version,
            "phone_brand": profile.phone_brand,
            "app_version": profile.app_version,
            "expected_next_order_date": profile.expected_next_order_date,
            "klaviyo_created_at": profile.klaviyo_created_at.isoformat() if profile.klaviyo_created_at else None,
            "klaviyo_updated_at": profile.klaviyo_updated_at.isoformat() if profile.klaviyo_updated_at else None,
            "last_event_at": profile.last_event_at.isoformat() if profile.last_event_at else None,
        },
        "recent_events": [
            {
                "metric": e.metric_name,
                "when": e.event_datetime.isoformat(),
                "properties": e.properties or {},
            }
            for e in events
        ],
    }


@router.get("/marketing-overview")
def marketing_overview(
    days: int = Query(30, ge=7, le=365),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Marketing-funnel view stitched from the mirrored Klaviyo data.

    Four rollups built from ``klaviyo_profiles`` and ``klaviyo_events``:

    * Signup timeseries — daily new profiles (``klaviyo_created_at``).
    * First-cook timeseries — daily First Cooking Session events; the
      downstream signal that installs are converting into real usage.
    * App engagement (DAU/MAU carry-through from the engagement
      endpoint) so the Marketing page has a standalone view.
    * Product Ownership breakdown — who buys what, which informs
      post-purchase flow performance.
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    signup_rows = db.execute(text("""
        SELECT
            (klaviyo_created_at AT TIME ZONE 'America/New_York')::date AS business_date,
            COUNT(*) AS n
        FROM klaviyo_profiles
        WHERE klaviyo_created_at >= :since
        GROUP BY 1 ORDER BY 1
    """), {"since": since}).all()

    first_cook_rows = db.execute(text("""
        SELECT
            (event_datetime AT TIME ZONE 'America/New_York')::date AS business_date,
            COUNT(*) AS n,
            COUNT(DISTINCT klaviyo_profile_id) AS unique_profiles
        FROM klaviyo_events
        WHERE metric_name = 'First Cooking Session'
          AND event_datetime >= :since
        GROUP BY 1 ORDER BY 1
    """), {"since": since}).all()

    order_rows = db.execute(text("""
        SELECT
            (event_datetime AT TIME ZONE 'America/New_York')::date AS business_date,
            COUNT(*) AS n,
            COUNT(DISTINCT klaviyo_profile_id) AS unique_profiles
        FROM klaviyo_events
        WHERE metric_name = 'Placed Order'
          AND event_datetime >= :since
        GROUP BY 1 ORDER BY 1
    """), {"since": since}).all()

    ownership_rows = db.execute(
        select(
            KlaviyoProfile.product_ownership,
            func.count().label("n"),
        )
        .where(KlaviyoProfile.product_ownership.isnot(None))
        .group_by(KlaviyoProfile.product_ownership)
        .order_by(func.count().desc())
    ).all()
    ownership_total = sum(int(r.n) for r in ownership_rows) or 1

    total_profiles = db.execute(select(func.count()).select_from(KlaviyoProfile)).scalar() or 0
    total_app_profiles = db.execute(
        select(func.count()).select_from(KlaviyoProfile).where(
            (KlaviyoProfile.app_version.isnot(None))
            | (KlaviyoProfile.phone_os.isnot(None))
            | (func.array_length(KlaviyoProfile.device_types, 1).isnot(None))
        )
    ).scalar() or 0

    return {
        "generated_at": now.isoformat(),
        "window_days": days,
        "total_profiles": int(total_profiles),
        "app_profiles": int(total_app_profiles),
        "app_install_rate_pct": round(int(total_app_profiles) / int(total_profiles) * 100.0, 1) if total_profiles else 0.0,
        "signups": [
            {"date": r.business_date.isoformat(), "count": int(r.n)}
            for r in signup_rows
        ],
        "first_cooks": [
            {"date": r.business_date.isoformat(), "events": int(r.n), "unique_profiles": int(r.unique_profiles or 0)}
            for r in first_cook_rows
        ],
        "orders": [
            {"date": r.business_date.isoformat(), "events": int(r.n), "unique_profiles": int(r.unique_profiles or 0)}
            for r in order_rows
        ],
        "product_ownership": [
            {"ownership": r.product_ownership, "count": int(r.n), "pct": round(int(r.n) / ownership_total * 100.0, 1)}
            for r in ownership_rows
        ],
    }


@router.get("/sync-status")
def sync_status(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Freshness indicator for the Klaviyo connector.

    UI cards read this to show a "Live · Updated N min ago" freshness
    bar so it's immediately obvious when the connector is behind.
    """
    last_profile = db.execute(
        select(func.max(KlaviyoProfile.klaviyo_updated_at))
    ).scalar()
    last_event = db.execute(
        select(func.max(KlaviyoEvent.event_datetime))
    ).scalar()
    profiles = db.execute(select(func.count()).select_from(KlaviyoProfile)).scalar() or 0
    events = db.execute(select(func.count()).select_from(KlaviyoEvent)).scalar() or 0
    events_by_metric = {
        r[0]: int(r[1])
        for r in db.execute(
            select(KlaviyoEvent.metric_name, func.count())
            .group_by(KlaviyoEvent.metric_name)
        ).all()
    }
    now = datetime.now(timezone.utc)
    return {
        "generated_at": now.isoformat(),
        "profiles_total": int(profiles),
        "events_total": int(events),
        "events_by_metric": events_by_metric,
        "latest_profile_updated_at": last_profile.isoformat() if last_profile else None,
        "latest_event_at": last_event.isoformat() if last_event else None,
        "profile_lag_minutes": int((now - last_profile).total_seconds() / 60) if last_profile else None,
        "event_lag_minutes": int((now - last_event).total_seconds() / 60) if last_event else None,
    }
