"""App-vs-telemetry reconciliation services for the PE page.

Two cards are powered from this module:

  • Cook reconciliation — compares the per-day count of Klaviyo
    ``Cook Completed`` events vs the telemetry-derived cook-session
    count (sum of ``cook_styles_json`` values in ``telemetry_history_daily``).
    A persistent gap in either direction is actionable:
      app > telemetry  → telemetry classifier is under-counting
                         (cooks happened, but cook_styles didn't tag them)
      app < telemetry  → app's Cook Completed event isn't firing
                         on every real cook (classifier sees a cook,
                         the app didn't report it)
    Plus rolls up:
      - completed_normally rate (true vs false)
      - duration distribution p50 / p75 / p95 (outliers >24h excluded)
      - target_temp histogram (low <250, mid 250-350, high 350+)

  • Pairing lifecycle — Klaviyo ``Device Paired`` and
    ``Device Unpaired`` events plus telemetry-active device count.
    Surfaces:
      - active-on-app device count (cumulative paired - unpaired)
      - pair-success rate vs telemetry-active devices
      - pair count by firmware_version  (badly-pairing FW surfaces)
      - pair count by device_type        (Kettle vs Huntsman split)

Both functions take a Session and a window-in-days. Both are read-only.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


# Cooks longer than 24h are clearly forgotten / never-ended sessions
# (e.g. the 244-hour cook the audit on 2026-04-28 surfaced). They
# poison percentiles, so we filter them at the SQL layer.
MAX_REAL_COOK_SECONDS = 24 * 3600


# Mac normalization. Telemetry side uses ``fc:b4:67:f9:ff:0a`` (with
# colons, mixed case); Klaviyo events use ``fcb467f9ff0a`` (12 hex
# chars, no separators). Strip everything non-hex and lowercase so
# both sides match. Used wherever we cross-reference the two streams.
def normalize_mac(s: Any) -> str | None:
    if s is None:
        return None
    cleaned = re.sub(r"[^0-9a-fA-F]", "", str(s)).lower()
    return cleaned or None


def cook_reconciliation(db: Session, days: int = 30) -> dict[str, Any]:
    """Per-day app-vs-telemetry cook counts plus app-side cook quality
    rollups (completed_normally, duration percentiles, target_temp bands).

    Returns:
        {
          "window_days": 30,
          "as_of": "2026-04-28",
          "daily": [
            {"business_date": "...", "app_cooks": int, "telemetry_cooks": int,
             "gap": int, "gap_pct": float | None},
            ...
          ],
          "totals": {
            "app_cooks": int,
            "telemetry_cooks": int,
            "gap": int,
            "completed_normally_pct": float | None,
            "completed_normally_n": int,
            "duration_p50_seconds": int | None,
            "duration_p75_seconds": int | None,
            "duration_p95_seconds": int | None,
            "long_cook_anomaly_count": int,   # >24h, excluded from percentiles
          },
          "target_temp_bands": {
            "low_below_250": int,
            "mid_250_to_350": int,
            "high_350_plus": int,
            "unknown": int,
          }
        }
    """
    if days <= 0:
        days = 30
    today = date.today()
    start_d = today - timedelta(days=days - 1)

    # Per-day telemetry cook count = sum of every classification bucket
    # in cook_styles_json. Daily roll-ups already exist; we just unwind
    # the JSON and sum.
    tele_rows = db.execute(text("""
        SELECT
            business_date,
            COALESCE((
                SELECT SUM((value)::int)
                FROM jsonb_each_text(cook_styles_json)
            ), 0) AS cooks
        FROM telemetry_history_daily
        WHERE business_date >= :start_d
        ORDER BY business_date
    """), {"start_d": start_d}).all()
    tele_by_date: dict[str, int] = {r.business_date.isoformat(): int(r.cooks or 0) for r in tele_rows}

    # Per-day app cook count from Klaviyo Cook Completed events.
    # We bucket by event_datetime in UTC date — close enough for the
    # daily comparison, and matches how telemetry_history_daily
    # business_date is materialized.
    app_rows = db.execute(text("""
        SELECT
            (event_datetime AT TIME ZONE 'UTC')::date AS business_date,
            COUNT(*) AS cooks
        FROM klaviyo_events
        WHERE metric_name = 'Cook Completed'
          AND event_datetime >= :start_dt
        GROUP BY 1
        ORDER BY 1
    """), {"start_dt": datetime.combine(start_d, datetime.min.time(), tzinfo=timezone.utc)}).all()
    app_by_date: dict[str, int] = {r.business_date.isoformat(): int(r.cooks or 0) for r in app_rows}

    # Build the unified daily series: every date in window, both counts.
    daily: list[dict[str, Any]] = []
    cursor = start_d
    while cursor <= today:
        key = cursor.isoformat()
        a = app_by_date.get(key, 0)
        t = tele_by_date.get(key, 0)
        gap = t - a
        gap_pct = (gap / t * 100.0) if t else None
        daily.append({
            "business_date": key,
            "app_cooks": a,
            "telemetry_cooks": t,
            "gap": gap,
            "gap_pct": round(gap_pct, 1) if gap_pct is not None else None,
        })
        cursor += timedelta(days=1)

    totals_app = sum(d["app_cooks"] for d in daily)
    totals_tele = sum(d["telemetry_cooks"] for d in daily)

    # App-side rollups: completed_normally rate + duration percentiles.
    # Properties JSONB has top-level keys; PostgreSQL extracts via ->>.
    # Note: ``completed_normally`` is sometimes JSON true/false (boolean)
    # and sometimes the string "true"/"false" depending on how Klaviyo
    # serialized it. Handle both via lowering-then-comparing.
    quality = db.execute(text("""
        WITH cooks AS (
            SELECT
                LOWER(properties->>'completed_normally') AS cn,
                NULLIF(properties->>'duration_seconds', '')::float AS dur,
                NULLIF(properties->>'target_temp', '')::float AS temp
            FROM klaviyo_events
            WHERE metric_name = 'Cook Completed'
              AND event_datetime >= :start_dt
        )
        SELECT
            COUNT(*) FILTER (WHERE cn = 'true') AS normal_count,
            COUNT(*) FILTER (WHERE cn IN ('true', 'false')) AS classified_count,
            COUNT(*) FILTER (WHERE dur IS NOT NULL AND dur > :max_dur) AS long_cook_anomalies,
            COUNT(*) FILTER (WHERE temp < 250) AS temp_low,
            COUNT(*) FILTER (WHERE temp >= 250 AND temp < 350) AS temp_mid,
            COUNT(*) FILTER (WHERE temp >= 350) AS temp_high,
            COUNT(*) FILTER (WHERE temp IS NULL) AS temp_unknown,
            percentile_disc(0.50) WITHIN GROUP (ORDER BY dur) FILTER (WHERE dur IS NOT NULL AND dur <= :max_dur) AS p50,
            percentile_disc(0.75) WITHIN GROUP (ORDER BY dur) FILTER (WHERE dur IS NOT NULL AND dur <= :max_dur) AS p75,
            percentile_disc(0.95) WITHIN GROUP (ORDER BY dur) FILTER (WHERE dur IS NOT NULL AND dur <= :max_dur) AS p95
        FROM cooks
    """), {
        "start_dt": datetime.combine(start_d, datetime.min.time(), tzinfo=timezone.utc),
        "max_dur": MAX_REAL_COOK_SECONDS,
    }).first()

    completed_normally_pct = None
    if quality and quality.classified_count:
        completed_normally_pct = round(100.0 * (quality.normal_count or 0) / quality.classified_count, 1)

    # When did the app start firing Cook Completed events at all?
    # Useful for the frontend to render an honest "events started
    # flowing on …" note — otherwise the daily chart looks broken on
    # the first ~30 days because the app side is all zeros even though
    # telemetry sees thousands of cooks.
    events_first_seen = db.execute(text("""
        SELECT MIN(event_datetime) AS first_seen
        FROM klaviyo_events
        WHERE metric_name = 'Cook Completed'
    """)).first()
    first_seen_iso = events_first_seen.first_seen.isoformat() if events_first_seen and events_first_seen.first_seen else None

    return {
        "window_days": days,
        "as_of": today.isoformat(),
        "events_first_seen_at": first_seen_iso,
        "daily": daily,
        "totals": {
            "app_cooks": totals_app,
            "telemetry_cooks": totals_tele,
            "gap": totals_tele - totals_app,
            "completed_normally_pct": completed_normally_pct,
            "completed_normally_n": int(quality.classified_count or 0) if quality else 0,
            "duration_p50_seconds": int(quality.p50) if quality and quality.p50 is not None else None,
            "duration_p75_seconds": int(quality.p75) if quality and quality.p75 is not None else None,
            "duration_p95_seconds": int(quality.p95) if quality and quality.p95 is not None else None,
            "long_cook_anomaly_count": int(quality.long_cook_anomalies or 0) if quality else 0,
        },
        "target_temp_bands": {
            "low_below_250": int(quality.temp_low or 0) if quality else 0,
            "mid_250_to_350": int(quality.temp_mid or 0) if quality else 0,
            "high_350_plus": int(quality.temp_high or 0) if quality else 0,
            "unknown": int(quality.temp_unknown or 0) if quality else 0,
        },
    }


def pairing_lifecycle(db: Session, days: int = 30) -> dict[str, Any]:
    """Pair / unpair counts, active-on-app device count, breakdowns by
    firmware version and device_type.

    Returns:
        {
          "window_days": 30,
          "as_of": "2026-04-28",
          "totals": {
            "pair_events": int,
            "unpair_events": int,
            "net_app_active": int,    # cumulative paired - unpaired in window
            "telemetry_active_devices_recent": int,   # latest engaged_devices reading
            "pair_success_rate_pct": float | None,    # pair events / telemetry-active
          },
          "by_device_type": [
            {"device_type": "Huntsman", "paired": N, "unpaired": N},
            ...
          ],
          "by_firmware": [
            {"firmware_version": "01.01.99", "paired": N, "unpaired": N},
            ...
          ],
          "recent_unpairs": [
            {"event_datetime": "...", "mac_normalized": "...",
             "device_type": "...", "firmware_version": "..."},
          ],
        }
    """
    if days <= 0:
        days = 30
    today = date.today()
    start_dt = datetime.combine(today - timedelta(days=days - 1), datetime.min.time(), tzinfo=timezone.utc)

    # Aggregate paired/unpaired counts in window. A single SQL pass covers
    # both metric types and both breakdowns by exposing the metric_name
    # alongside each event.
    by_type = db.execute(text("""
        SELECT
            metric_name,
            COALESCE(NULLIF(properties->>'device_type', ''), 'unknown') AS device_type,
            COUNT(*) AS n
        FROM klaviyo_events
        WHERE metric_name IN ('Device Paired', 'Device Unpaired')
          AND event_datetime >= :start_dt
        GROUP BY metric_name, device_type
        ORDER BY device_type
    """), {"start_dt": start_dt}).all()

    by_firmware = db.execute(text("""
        SELECT
            metric_name,
            COALESCE(NULLIF(properties->>'firmware_version', ''), 'unknown') AS firmware_version,
            COUNT(*) AS n
        FROM klaviyo_events
        WHERE metric_name IN ('Device Paired', 'Device Unpaired')
          AND event_datetime >= :start_dt
        GROUP BY metric_name, firmware_version
        ORDER BY firmware_version DESC
    """), {"start_dt": start_dt}).all()

    pair_events = sum(int(r.n) for r in by_type if r.metric_name == "Device Paired")
    unpair_events = sum(int(r.n) for r in by_type if r.metric_name == "Device Unpaired")

    # Telemetry-active device baseline. Use the most recent
    # engaged_devices reading from the last completed business day —
    # gives us a stable denominator the dashboard already trusts.
    tele_active_row = db.execute(text("""
        SELECT engaged_devices
        FROM telemetry_history_daily
        WHERE business_date >= CURRENT_DATE - 7
        ORDER BY business_date DESC
        LIMIT 1
    """)).first()
    tele_active = int(tele_active_row.engaged_devices) if tele_active_row else 0
    pair_success_pct = None
    if tele_active > 0:
        pair_success_pct = round(100.0 * pair_events / tele_active, 1)

    # Build merged per-bucket views. Each bucket gets paired + unpaired
    # counts for the same key.
    def _merge(rows: Any, key: str) -> list[dict[str, Any]]:
        bucket: dict[str, dict[str, int]] = {}
        for r in rows:
            k = getattr(r, key)
            bucket.setdefault(k, {"paired": 0, "unpaired": 0})
            if r.metric_name == "Device Paired":
                bucket[k]["paired"] += int(r.n)
            elif r.metric_name == "Device Unpaired":
                bucket[k]["unpaired"] += int(r.n)
        out = [{key: k, "paired": v["paired"], "unpaired": v["unpaired"]} for k, v in bucket.items()]
        # Surface largest cohorts first.
        out.sort(key=lambda d: -(d["paired"] + d["unpaired"]))
        return out

    # Recent unpairs — the audit-friendly sample. Last 5 events with
    # the meta we have so leads can spot-check who's leaving.
    recent_unpairs_rows = db.execute(text("""
        SELECT
            event_datetime,
            properties->>'mac' AS mac,
            properties->>'device_type' AS device_type,
            properties->>'firmware_version' AS firmware_version
        FROM klaviyo_events
        WHERE metric_name = 'Device Unpaired'
          AND event_datetime >= :start_dt
        ORDER BY event_datetime DESC
        LIMIT 5
    """), {"start_dt": start_dt}).all()
    recent_unpairs = [
        {
            "event_datetime": r.event_datetime.isoformat() if r.event_datetime else None,
            "mac_normalized": normalize_mac(r.mac),
            "device_type": r.device_type or "unknown",
            "firmware_version": r.firmware_version or "unknown",
        }
        for r in recent_unpairs_rows
    ]

    return {
        "window_days": days,
        "as_of": today.isoformat(),
        "totals": {
            "pair_events": pair_events,
            "unpair_events": unpair_events,
            "net_app_active": pair_events - unpair_events,
            "telemetry_active_devices_recent": tele_active,
            "pair_success_rate_pct": pair_success_pct,
        },
        "by_device_type": _merge(by_type, "device_type"),
        "by_firmware": _merge(by_firmware, "firmware_version")[:8],
        "recent_unpairs": recent_unpairs,
    }
