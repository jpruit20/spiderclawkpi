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


@router.get("/install-to-first-cook")
def install_to_first_cook(
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Conversion + time-to-first-cook funnel.

    The app-side product question: when somebody installs the
    Spider Grills app, how often does it lead to an actual first
    cook, and how long does it take?

    Methodology:

    * "Installed" = profile that has fired at least one ``Opened App``
      event (so we know the SDK initialized) and whose
      ``klaviyo_created_at`` timestamp is the install anchor.
    * "First cook" = the same profile fired ``First Cooking Session``
      at some later timestamp.
    * Time-to-first-cook = days between install and first-cook event.

    Reports overall conversion + a histogram of time-to-first-cook
    bucketed into 0d / 1d / 2-3d / 4-7d / 8-14d / 15-30d / 30d+.
    """
    rows = db.execute(text("""
        WITH installs AS (
            SELECT DISTINCT ON (klaviyo_profile_id)
                klaviyo_profile_id,
                MIN(event_datetime) AS first_open_at
            FROM klaviyo_events
            WHERE metric_name = 'Opened App'
              AND klaviyo_profile_id IS NOT NULL
            GROUP BY klaviyo_profile_id
        ),
        first_cooks AS (
            SELECT
                klaviyo_profile_id,
                MIN(event_datetime) AS first_cook_at
            FROM klaviyo_events
            WHERE metric_name = 'First Cooking Session'
              AND klaviyo_profile_id IS NOT NULL
            GROUP BY klaviyo_profile_id
        )
        SELECT
            COUNT(*) AS installed,
            COUNT(c.klaviyo_profile_id) AS converted,
            COUNT(*) FILTER (
                WHERE c.first_cook_at IS NOT NULL
                  AND EXTRACT(EPOCH FROM (c.first_cook_at - i.first_open_at)) < 86400
            ) AS within_1d,
            COUNT(*) FILTER (
                WHERE c.first_cook_at IS NOT NULL
                  AND EXTRACT(EPOCH FROM (c.first_cook_at - i.first_open_at)) BETWEEN 86400 AND 86400*3
            ) AS within_3d,
            COUNT(*) FILTER (
                WHERE c.first_cook_at IS NOT NULL
                  AND EXTRACT(EPOCH FROM (c.first_cook_at - i.first_open_at)) BETWEEN 86400*3 AND 86400*7
            ) AS within_7d,
            COUNT(*) FILTER (
                WHERE c.first_cook_at IS NOT NULL
                  AND EXTRACT(EPOCH FROM (c.first_cook_at - i.first_open_at)) BETWEEN 86400*7 AND 86400*14
            ) AS within_14d,
            COUNT(*) FILTER (
                WHERE c.first_cook_at IS NOT NULL
                  AND EXTRACT(EPOCH FROM (c.first_cook_at - i.first_open_at)) BETWEEN 86400*14 AND 86400*30
            ) AS within_30d,
            COUNT(*) FILTER (
                WHERE c.first_cook_at IS NOT NULL
                  AND EXTRACT(EPOCH FROM (c.first_cook_at - i.first_open_at)) > 86400*30
            ) AS beyond_30d,
            PERCENTILE_DISC(0.50) WITHIN GROUP (
                ORDER BY EXTRACT(EPOCH FROM (c.first_cook_at - i.first_open_at))
            ) FILTER (WHERE c.first_cook_at IS NOT NULL) AS median_seconds
        FROM installs i
        LEFT JOIN first_cooks c USING (klaviyo_profile_id)
    """)).first()

    installed = int(rows.installed or 0)
    converted = int(rows.converted or 0)
    median_seconds = float(rows.median_seconds) if rows.median_seconds is not None else None

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "installed": installed,
        "converted_to_first_cook": converted,
        "conversion_pct": round(converted / installed * 100.0, 1) if installed else 0.0,
        "median_days_to_first_cook": round(median_seconds / 86400, 1) if median_seconds is not None else None,
        "histogram": [
            {"bucket": "Same day", "count": int(rows.within_1d or 0)},
            {"bucket": "1-3 days", "count": int(rows.within_3d or 0)},
            {"bucket": "3-7 days", "count": int(rows.within_7d or 0)},
            {"bucket": "1-2 weeks", "count": int(rows.within_14d or 0)},
            {"bucket": "2-4 weeks", "count": int(rows.within_30d or 0)},
            {"bucket": "30+ days", "count": int(rows.beyond_30d or 0)},
        ],
    }


@router.get("/engagement-by-ownership")
def engagement_by_ownership(
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """DAU/MAU split by Product Ownership tag.

    Answers: do Huntsman owners use the app more than Kettle/Webcraft
    owners? Helps prioritize which segments to invest app-feature
    work into.
    """
    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(days=1)
    cutoff_30d = now - timedelta(days=30)

    rows = db.execute(text("""
        SELECT
            COALESCE(p.product_ownership, 'Unknown') AS ownership,
            COUNT(DISTINCT p.klaviyo_id) AS profiles,
            COUNT(DISTINCT p.klaviyo_id) FILTER (
                WHERE EXISTS (
                    SELECT 1 FROM klaviyo_events e
                    WHERE e.klaviyo_profile_id = p.klaviyo_id
                      AND e.metric_name = 'Opened App'
                      AND e.event_datetime >= :cutoff_24h
                )
            ) AS dau,
            COUNT(DISTINCT p.klaviyo_id) FILTER (
                WHERE EXISTS (
                    SELECT 1 FROM klaviyo_events e
                    WHERE e.klaviyo_profile_id = p.klaviyo_id
                      AND e.metric_name = 'Opened App'
                      AND e.event_datetime >= :cutoff_30d
                )
            ) AS mau
        FROM klaviyo_profiles p
        WHERE p.app_version IS NOT NULL
           OR p.phone_os IS NOT NULL
           OR array_length(p.device_types, 1) IS NOT NULL
        GROUP BY p.product_ownership
        ORDER BY profiles DESC
    """), {"cutoff_24h": cutoff_24h, "cutoff_30d": cutoff_30d}).all()

    return {
        "generated_at": now.isoformat(),
        "by_ownership": [
            {
                "ownership": r.ownership,
                "profiles": int(r.profiles or 0),
                "dau": int(r.dau or 0),
                "mau": int(r.mau or 0),
                "stickiness_pct": round((int(r.dau or 0) / int(r.mau)) * 100.0, 1) if r.mau else 0.0,
            }
            for r in rows
        ],
    }


@router.get("/recent-events")
def recent_events(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Live activity feed — last N app events with profile context.

    Powers an ops-style scrolling feed of "what users are doing in
    the app right now". Joins to klaviyo_profiles so each row carries
    enough identity to be useful (email + product ownership).
    """
    rows = db.execute(text("""
        SELECT
            e.klaviyo_event_id,
            e.metric_name,
            e.event_datetime,
            p.email,
            p.external_id,
            p.product_ownership,
            p.device_types,
            p.phone_os
        FROM klaviyo_events e
        LEFT JOIN klaviyo_profiles p ON p.klaviyo_id = e.klaviyo_profile_id
        ORDER BY e.event_datetime DESC
        LIMIT :limit
    """), {"limit": limit}).all()

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events": [
            {
                "event_id": r.klaviyo_event_id,
                "metric": r.metric_name,
                "when": r.event_datetime.isoformat() if r.event_datetime else None,
                "email": r.email,
                "external_id": r.external_id,
                "product_ownership": r.product_ownership,
                "device_types": r.device_types or [],
                "phone_os": r.phone_os,
            }
            for r in rows
        ],
    }


_marketing_cache: dict[str, tuple[float, Any]] = {}
_MARKETING_CACHE_TTL = 1800  # 30 min


def _scope_error(exc: Exception) -> Optional[str]:
    """Return the missing-scope detail when the wrapped Klaviyo call
    raised a 403 because the configured API key is too narrow. Lets
    endpoints render a friendly "add this scope" hint instead of a
    plain 500 — the dashboard stays usable while the operator adds
    scopes in Klaviyo's admin UI."""
    msg = str(exc)
    if "Klaviyo API 403" not in msg:
        return None
    # Klaviyo's body looks like ``... missing required scopes: campaigns:read``
    import re
    m = re.search(r"missing required scopes:\s*([^\"\\}]+)", msg)
    if m:
        return m.group(1).strip()
    return "unknown"


def _cached_klaviyo(key: str, fn: Any) -> Any:
    """Tiny in-memory TTL cache for Klaviyo proxy responses.

    Marketing data (campaigns, flows, lists, segments) doesn't change
    minute-to-minute, but the underlying Klaviyo API endpoints are slow
    and rate-limited. 30 min TTL keeps the dashboard snappy without
    hammering Klaviyo.
    """
    import time as _time
    now = _time.monotonic()
    hit = _marketing_cache.get(key)
    if hit is not None and now - hit[0] < _MARKETING_CACHE_TTL:
        return hit[1]
    value = fn()
    _marketing_cache[key] = (now, value)
    return value


@router.get("/campaigns-recent")
def campaigns_recent(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Recent email campaigns (last 90d) with aggregate stats.

    Pulled live from Klaviyo with a 30-min cache. Includes metadata
    for each campaign — open rate, click rate, recipients — when
    Klaviyo has finished tabulating it. Send-in-progress campaigns
    show with ``status='Sending'`` and partial stats.
    """
    from app.ingestion.connectors.klaviyo import _get, _paginate

    def _fetch() -> list[dict[str, Any]]:
        # NB: Klaviyo's /campaigns, /flows, /lists, /segments endpoints
        # all reject `page[size]` (verified 2026-04-25 via 400 response —
        # "page_size is not a valid field for the resource"). They use
        # the cursor-based default page size and we follow links.next.
        # /campaigns *does* require a channel filter — without it the
        # API returns 400 even on bare GETs.
        cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
        params = {
            "filter": f"and(equals(messages.channel,\"email\"),greater-or-equal(scheduled_at,{cutoff}))",
            "sort": "-scheduled_at",
            "fields[campaign]": "name,status,send_time,scheduled_at,created_at,updated_at,send_strategy",
        }
        out: list[dict[str, Any]] = []
        for page in _paginate("/campaigns", params):
            for row in page.get("data") or []:
                a = row.get("attributes") or {}
                out.append({
                    "id": row.get("id"),
                    "name": a.get("name"),
                    "status": a.get("status"),
                    "scheduled_at": a.get("scheduled_at"),
                    "send_time": a.get("send_time"),
                    "created_at": a.get("created_at"),
                    "updated_at": a.get("updated_at"),
                })
                if len(out) >= limit:
                    break
            if len(out) >= limit:
                break
        return out

    try:
        rows = _cached_klaviyo(f"campaigns:{limit}", _fetch)
    except Exception as exc:
        scope = _scope_error(exc)
        if scope:
            return {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "campaigns": [],
                "missing_scope": scope,
                "note": f"Add the {scope} scope to KLAVIYO_API_KEY at https://www.klaviyo.com/account#api-keys-tab to populate this view.",
            }
        raise
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "campaigns": rows,
    }


@router.get("/flows-status")
def flows_status(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Status snapshot of every configured flow.

    Each flow row carries name, status (live/draft/manual), trigger
    type (Added to List / Metric / Date / etc.), and updated
    timestamp. Surfaces stalled drafts and the live automation
    population at a glance.
    """
    from app.ingestion.connectors.klaviyo import _paginate

    def _fetch() -> list[dict[str, Any]]:
        params = {
            "fields[flow]": "name,status,trigger_type,created,updated",
        }
        out: list[dict[str, Any]] = []
        for page in _paginate("/flows", params):
            for row in page.get("data") or []:
                a = row.get("attributes") or {}
                out.append({
                    "id": row.get("id"),
                    "name": a.get("name"),
                    "status": a.get("status"),
                    "trigger_type": a.get("triggerType") or a.get("trigger_type"),
                    "created": a.get("created"),
                    "updated": a.get("updated"),
                })
        return out

    try:
        rows = _cached_klaviyo("flows", _fetch)
    except Exception as exc:
        scope = _scope_error(exc)
        if scope:
            return {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "by_status": {},
                "flows": [],
                "missing_scope": scope,
                "note": f"Add the {scope} scope to KLAVIYO_API_KEY at https://www.klaviyo.com/account#api-keys-tab to populate this view.",
            }
        raise
    by_status: dict[str, int] = {}
    for r in rows:
        s = r.get("status") or "unknown"
        by_status[s] = by_status.get(s, 0) + 1
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "by_status": by_status,
        "flows": sorted(rows, key=lambda r: (r.get("status") != "live", r.get("name") or "")),
    }


@router.get("/lists-and-segments")
def lists_and_segments(db: Session = Depends(db_session)) -> dict[str, Any]:
    """All Klaviyo lists + segments with current membership.

    Lists are explicit subscriber rosters (Beta Customers, Huntsman
    Giveaway, etc.). Segments are dynamic queries (App active users,
    Huntsman Purchasers All Time). Both carry a member count so the
    Marketing team can see roster health and the dashboard can pull
    list/segment IDs for downstream integrations (e.g. the Firmware
    Beta Program reads the Beta Customers list).

    Member counts come from a per-row count call to Klaviyo because
    the list/segment endpoints don't inline it. Cached 30 min.
    """
    from app.ingestion.connectors.klaviyo import _get, _paginate

    def _fetch() -> dict[str, list[dict[str, Any]]]:
        lists: list[dict[str, Any]] = []
        for page in _paginate("/lists", None):
            for row in page.get("data") or []:
                a = row.get("attributes") or {}
                lists.append({
                    "id": row.get("id"),
                    "name": a.get("name"),
                    "opt_in_process": a.get("optInProcess") or a.get("opt_in_process"),
                    "created": a.get("created"),
                    "updated": a.get("updated"),
                })
        segments: list[dict[str, Any]] = []
        for page in _paginate("/segments", None):
            for row in page.get("data") or []:
                a = row.get("attributes") or {}
                segments.append({
                    "id": row.get("id"),
                    "name": a.get("name"),
                    "is_active": a.get("isActive"),
                    "is_processing": a.get("isProcessing"),
                    "created": a.get("created"),
                    "updated": a.get("updated"),
                })
        # Membership count per object — small N (typical account has
        # <50 of each) so a sequential walk is fine inside the 30-min
        # cache window.
        # /lists/{id}/profiles and /segments/{id}/profiles also reject
        # page[size]; we just take the first page and trust the meta
        # block for the count. ``additional-fields[list]=profile_count``
        # would be cleaner but isn't on every Klaviyo plan.
        for row in lists:
            try:
                resp = _get(f"/lists/{row['id']}/profiles")
                meta = (resp.get("meta") or {})
                row["member_count"] = int((meta.get("filterCount") or meta.get("filter_count") or len(resp.get("data") or [])))
            except Exception:
                row["member_count"] = None
        for row in segments:
            try:
                resp = _get(f"/segments/{row['id']}/profiles")
                meta = (resp.get("meta") or {})
                row["member_count"] = int((meta.get("filterCount") or meta.get("filter_count") or len(resp.get("data") or [])))
            except Exception:
                row["member_count"] = None
        return {"lists": lists, "segments": segments}

    payload = _cached_klaviyo("lists_segments", _fetch)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **payload,
    }


@router.get("/beta-customers")
def beta_customers(
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Members of Klaviyo's "Beta Customers" list.

    Joseph and the marketing team curate this list inside Klaviyo;
    the Firmware Beta Program reads it here as the canonical opt-in
    cohort. Joins each member's email back to ``klaviyo_profiles`` to
    pull device + firmware context, so the firmware team can see
    the cohort's actual hardware spread before pushing an OTA.

    The list ID is resolved by name on the fly, so renaming or
    duplicating the list in Klaviyo just requires updating it there.
    """
    from app.ingestion.connectors.klaviyo import _get, _paginate

    def _fetch_list_id() -> Optional[str]:
        for page in _paginate("/lists", None):
            for row in page.get("data") or []:
                a = row.get("attributes") or {}
                if (a.get("name") or "").strip().lower() == "beta customers":
                    return row.get("id")
        return None

    list_id = _cached_klaviyo("beta_list_id", _fetch_list_id)
    if not list_id:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "list_id": None,
            "error": "no list named 'Beta Customers' found in Klaviyo",
            "members": [],
        }

    def _fetch_members() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        params = {
            "fields[profile]": "email,external_id,first_name,last_name,properties,last_event_date",
        }
        for page in _paginate(f"/lists/{list_id}/profiles", params):
            for row in page.get("data") or []:
                a = row.get("attributes") or {}
                props = a.get("properties") or {}
                out.append({
                    "klaviyo_id": row.get("id"),
                    "email": a.get("email"),
                    "external_id": a.get("externalId") or a.get("external_id"),
                    "first_name": a.get("firstName") or a.get("first_name"),
                    "last_name": a.get("lastName") or a.get("last_name"),
                    "device_types": props.get("deviceTypes") or [],
                    "device_firmware_versions": props.get("deviceFirmwareVersions") or [],
                    "product_ownership": props.get("Product Ownership"),
                    "phone_os": props.get("phoneOS"),
                    "app_version": props.get("appVersion"),
                    "last_event_date": a.get("lastEventDate") or a.get("last_event_date"),
                })
                if len(out) >= limit:
                    return out
        return out

    members = _cached_klaviyo(f"beta_members:{list_id}:{limit}", _fetch_members)

    # Roll up firmware + device-type distribution for the cohort —
    # that's the firmware team's most-asked-for view of an opt-in list.
    fw_counts: dict[str, int] = {}
    dt_counts: dict[str, int] = {}
    os_counts: dict[str, int] = {}
    for m in members:
        for fw in m.get("device_firmware_versions") or []:
            fw_counts[fw] = fw_counts.get(fw, 0) + 1
        for dt in m.get("device_types") or []:
            dt_counts[dt] = dt_counts.get(dt, 0) + 1
        if m.get("phone_os"):
            os_counts[m["phone_os"]] = os_counts.get(m["phone_os"], 0) + 1

    def _top(d: dict[str, int]) -> list[dict[str, Any]]:
        total = sum(d.values()) or 1
        return [
            {"label": k, "count": v, "pct": round(v / total * 100.0, 1)}
            for k, v in sorted(d.items(), key=lambda kv: kv[1], reverse=True)
        ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "list_id": list_id,
        "total_members": len(members),
        "members": members,
        "firmware_distribution": _top(fw_counts),
        "device_type_distribution": _top(dt_counts),
        "phone_os_distribution": _top(os_counts),
    }


@router.get("/friendbuy-attribution")
def friendbuy_attribution(
    days: int = Query(30, ge=7, le=365),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Friendbuy referral signal pulled from Klaviyo profile properties.

    The Friendbuy app populates ``Friendbuy Customer Name`` /
    ``Friendbuy Campaign Name`` / ``Friendbuy Referral Link`` on
    every profile that has been issued a referral code, plus separate
    ``Friendbuy - Referral Created`` / ``Referral Shared`` /
    ``Advocate Reward Earned`` / ``Friend Incentive Earned`` events
    when actions fire. Together they tell us how much of the recent
    customer base came in through referrals and which campaigns
    drove the most.
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    total_profiles = db.execute(select(func.count()).select_from(KlaviyoProfile)).scalar() or 0
    with_friendbuy_tag = db.execute(text("""
        SELECT COUNT(*) FROM klaviyo_profiles
        WHERE raw_properties ? 'Friendbuy Customer Name'
           OR raw_properties ? 'Friendbuy Campaign Name'
    """)).scalar() or 0

    new_in_window = db.execute(text("""
        SELECT COUNT(*) FROM klaviyo_profiles
        WHERE klaviyo_created_at >= :since
    """), {"since": since}).scalar() or 0
    new_friendbuy_in_window = db.execute(text("""
        SELECT COUNT(*) FROM klaviyo_profiles
        WHERE klaviyo_created_at >= :since
          AND (raw_properties ? 'Friendbuy Customer Name'
               OR raw_properties ? 'Friendbuy Campaign Name')
    """), {"since": since}).scalar() or 0

    campaign_rows = db.execute(text("""
        SELECT
            raw_properties->>'Friendbuy Campaign Name' AS campaign,
            COUNT(*) AS profiles
        FROM klaviyo_profiles
        WHERE raw_properties->>'Friendbuy Campaign Name' IS NOT NULL
        GROUP BY 1
        ORDER BY 2 DESC
        LIMIT 10
    """)).all()

    return {
        "generated_at": now.isoformat(),
        "window_days": days,
        "total_profiles": int(total_profiles),
        "profiles_with_friendbuy_tag": int(with_friendbuy_tag),
        "tag_rate_pct": round(int(with_friendbuy_tag) / int(total_profiles) * 100.0, 1) if total_profiles else 0.0,
        "new_in_window": int(new_in_window),
        "new_friendbuy_in_window": int(new_friendbuy_in_window),
        "friendbuy_share_of_new_pct": round(int(new_friendbuy_in_window) / int(new_in_window) * 100.0, 1) if new_in_window else 0.0,
        "top_campaigns": [
            {"campaign": r.campaign, "profiles": int(r.profiles)}
            for r in campaign_rows
        ],
    }


@router.get("/customer-journey")
def customer_journey(
    email: Optional[str] = Query(default=None),
    external_id: Optional[str] = Query(default=None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Full chronological journey for one customer.

    Pulls every mirrored Klaviyo event for the profile in event-time
    order, oldest first. The CX team uses this when escalating a
    ticket — "what happened before they hit support?" answered in
    one call.
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
        return {"found": False, "email": email, "external_id": external_id}

    events = db.execute(
        select(
            KlaviyoEvent.metric_name,
            KlaviyoEvent.event_datetime,
            KlaviyoEvent.properties,
        )
        .where(KlaviyoEvent.klaviyo_profile_id == profile.klaviyo_id)
        .order_by(KlaviyoEvent.event_datetime.asc())
        .limit(limit)
    ).all()

    # Bucket events by month so the UI can render a stacked timeline.
    by_month: dict[str, dict[str, int]] = {}
    for e in events:
        month = e.event_datetime.strftime("%Y-%m")
        by_month.setdefault(month, {})
        by_month[month][e.metric_name] = by_month[month].get(e.metric_name, 0) + 1

    return {
        "found": True,
        "profile": {
            "klaviyo_id": profile.klaviyo_id,
            "email": profile.email,
            "external_id": profile.external_id,
            "first_name": profile.first_name,
            "last_name": profile.last_name,
            "device_types": profile.device_types,
            "device_firmware_versions": profile.device_firmware_versions,
            "product_ownership": profile.product_ownership,
            "phone_os": profile.phone_os,
            "app_version": profile.app_version,
            "klaviyo_created_at": profile.klaviyo_created_at.isoformat() if profile.klaviyo_created_at else None,
        },
        "event_count": len(events),
        "events": [
            {
                "metric": e.metric_name,
                "when": e.event_datetime.isoformat(),
                "properties": e.properties or {},
            }
            for e in events
        ],
        "by_month": [
            {"month": m, "counts": counts}
            for m, counts in sorted(by_month.items())
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
