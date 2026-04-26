"""Klaviyo audience taxonomy.

Joseph's 2026-04-26 callout: the dashboard was conflating three very
different populations and presenting them all as "customers". This
service is the single source of truth for the four buckets we
actually care about, so every card and recommendation can use the
right denominator.

Buckets, definitions, and the signal each is derived from:

* **Total audience** — every Klaviyo profile. Includes newsletter
  signups, giveaway entrants, abandoned-cart shoppers, deal hunters,
  curious lurkers, etc. Is NOT the customer base. Source: row count
  on ``klaviyo_profiles``.

* **Owners** — profiles that have actually purchased a Spider Grills
  product. Three signals are unioned because no single one catches
  everyone:

    1. ``klaviyo_events`` rows for ``Placed Order`` events whose
       ``properties.Items`` array contains a Spider product name
       (Huntsman / Venom / Webcraft / Kettle Cart variants).
    2. ``klaviyo_profiles.product_ownership`` set (Klaviyo's own tag).
    3. ``klaviyo_profiles.device_types`` array non-empty (signal from
       the app — only set after the user paired a device).

* **App users** — profiles that have ever fired the ``Opened App``
  event (since Klaviyo SDK install on 2025-06-20). The MOST reliable
  signal that someone actually installed and used the app.

* **Connected devices** — distinct ``device_id`` values that have
  ever shown up in ``telemetry_sessions``. This is the FLEET (~7.5k
  units), not a profile count. Reported alongside the others so
  Joseph can see the device-vs-profile reconciliation in one place.

The "app users" count is intentionally lower than "connected
devices" because:
  - Klaviyo SDK only started firing in mid-2025; pre-2025 app users
    don't have an Opened App event
  - Many households have multiple devices on one app account
  - Some users uninstalled the app after pairing

This module is read-only and side-effect free. It can be called
freely from API routes; one call ~50-200ms thanks to indexed counts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


SPIDER_PRODUCT_NEEDLES = (
    "huntsman",
    "venom",
    "webcraft",
    "kettle cart",
    "spider grills",
)


def _spider_product_filter_sql() -> str:
    """LOWER+LIKE OR-chain matching any Spider product name in the
    ``Items`` array of a Placed Order event's properties. Cast to
    text once so a single ILIKE pass over the JSONB blob picks up any
    variant of the product name (Huntsman / The Huntsman™ / GIANT
    HUNTSMAN / Webcraft Elite Series / Kettle Cart for 22" Weber
    Kettles / etc.)."""
    clauses = [
        f"LOWER(properties::text) LIKE '%{n}%'"
        for n in SPIDER_PRODUCT_NEEDLES
    ]
    return "(" + " OR ".join(clauses) + ")"


def count_total_profiles(db: Session) -> int:
    return int(db.execute(text("SELECT COUNT(*) FROM klaviyo_profiles")).scalar() or 0)


def count_app_users(db: Session) -> int:
    """Profiles that have ever fired Opened App."""
    return int(db.execute(text("""
        SELECT COUNT(DISTINCT klaviyo_profile_id)
        FROM klaviyo_events
        WHERE metric_name = 'Opened App'
          AND klaviyo_profile_id IS NOT NULL
    """)).scalar() or 0)


def count_active_app_users(db: Session, days: int = 30) -> int:
    return int(db.execute(text(f"""
        SELECT COUNT(DISTINCT klaviyo_profile_id)
        FROM klaviyo_events
        WHERE metric_name = 'Opened App'
          AND klaviyo_profile_id IS NOT NULL
          AND event_datetime >= NOW() - INTERVAL '{int(days)} days'
    """)).scalar() or 0)


def count_owners(db: Session) -> dict[str, int]:
    """Three sources of owner signal, plus the deduplicated union.

    Returns ``{by_order, by_klaviyo_tag, by_device_types, total}``
    where ``total`` is the cardinality of the union (each profile
    counted once even if multiple signals match).
    """
    spider_filter = _spider_product_filter_sql()
    by_order = int(db.execute(text(f"""
        SELECT COUNT(DISTINCT klaviyo_profile_id)
        FROM klaviyo_events
        WHERE metric_name = 'Placed Order'
          AND klaviyo_profile_id IS NOT NULL
          AND {spider_filter}
    """)).scalar() or 0)

    by_tag = int(db.execute(text("""
        SELECT COUNT(*)
        FROM klaviyo_profiles
        WHERE product_ownership IS NOT NULL
          AND product_ownership <> ''
    """)).scalar() or 0)

    by_device_types = int(db.execute(text("""
        SELECT COUNT(*)
        FROM klaviyo_profiles
        WHERE array_length(device_types, 1) IS NOT NULL
    """)).scalar() or 0)

    union_total = int(db.execute(text(f"""
        SELECT COUNT(DISTINCT klaviyo_id)
        FROM (
            SELECT p.klaviyo_id FROM klaviyo_profiles p
            WHERE p.product_ownership IS NOT NULL AND p.product_ownership <> ''
            UNION
            SELECT p.klaviyo_id FROM klaviyo_profiles p
            WHERE array_length(p.device_types, 1) IS NOT NULL
            UNION
            SELECT DISTINCT klaviyo_profile_id AS klaviyo_id
            FROM klaviyo_events
            WHERE metric_name = 'Placed Order'
              AND klaviyo_profile_id IS NOT NULL
              AND {spider_filter}
        ) t
    """)).scalar() or 0)

    return {
        "by_order": by_order,
        "by_klaviyo_tag": by_tag,
        "by_device_types": by_device_types,
        "total": union_total,
    }


def count_connected_devices(db: Session) -> dict[str, int]:
    """Lifetime + recent device counts from telemetry_sessions.

    This is a fleet metric (devices), not a profile metric. Reported
    here so the Marketing/PE pages can show device-vs-profile
    reconciliation in one place.
    """
    lifetime = int(db.execute(text("""
        SELECT COUNT(DISTINCT device_id)
        FROM telemetry_sessions
        WHERE device_id IS NOT NULL
          AND device_id NOT LIKE 'mac:%'
    """)).scalar() or 0)
    last_24mo = int(db.execute(text("""
        SELECT COUNT(DISTINCT device_id)
        FROM telemetry_sessions
        WHERE device_id IS NOT NULL
          AND device_id NOT LIKE 'mac:%'
          AND session_start >= NOW() - INTERVAL '730 days'
    """)).scalar() or 0)
    return {"lifetime": lifetime, "last_24mo": last_24mo}


def audience_segmentation(db: Session) -> dict[str, Any]:
    """One-call summary that powers the audience-segmentation card."""
    total = count_total_profiles(db)
    app = count_app_users(db)
    app_30d = count_active_app_users(db, days=30)
    owners = count_owners(db)
    devices = count_connected_devices(db)

    def _pct(num: int, denom: int) -> float:
        return round(num / denom * 100.0, 1) if denom else 0.0

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_audience": total,
        "owners": {
            **owners,
            "pct_of_audience": _pct(owners["total"], total),
        },
        "app_users": {
            "lifetime": app,
            "active_30d": app_30d,
            "pct_of_owners": _pct(app, owners["total"]) if owners["total"] else 0.0,
            "pct_of_audience": _pct(app, total),
        },
        "connected_devices": devices,
        "device_to_app_user_ratio": (
            round(devices["lifetime"] / app, 2) if app else None
        ),
        "non_owner_audience": max(0, total - owners["total"]),
        "non_owner_pct": _pct(total - owners["total"], total),
    }
