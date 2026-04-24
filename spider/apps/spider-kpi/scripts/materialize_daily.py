#!/usr/bin/env python3
"""Materialize daily aggregates from telemetry_stream_events into telemetry_history_daily.

Designed to run nightly via systemd timer or cron. Computes per-day metrics from
the live stream events table and upserts them into the history table, preserving
richer S3 backfill rows unless --force is given.

Usage:
    python materialize_daily.py                  # last 7 days
    python materialize_daily.py --days-back 30   # last 30 days
    python materialize_daily.py --force           # overwrite even if existing data is richer
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

# Allow imports from backend/app
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.cook_classification import EventRow, derive_sessions_from_rows, build_daily_cook_columns
from app.services.product_taxonomy import (
    FAMILY_UNKNOWN,
    classify_product,
    _norm_fw,
    JOEHY_MODEL,
    T2_MAX_HUNTSMAN,
    T2_MAX_WEBER_KETTLE,
)

# ---------------------------------------------------------------------------
# .env loading
# ---------------------------------------------------------------------------

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader -- sets vars that are not already in the environment."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)", line)
        if not match:
            continue
        key, value = match.group(1), match.group(2)
        # Strip optional surrounding quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _dsn_from_env() -> str:
    """Return a libpq-compatible DSN from DATABASE_URL.

    The .env may use a SQLAlchemy-style ``postgresql+psycopg://`` scheme.
    psycopg3 expects a plain ``postgresql://`` scheme.
    """
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL is not set in environment or .env")
    # Normalise scheme: strip +driver suffix that SQLAlchemy uses
    url = re.sub(r"^postgresql\+\w+://", "postgresql://", url)
    return url


# ---------------------------------------------------------------------------
# Aggregation query
# ---------------------------------------------------------------------------

AGGREGATE_SQL = """\
SELECT
    (sample_timestamp AT TIME ZONE 'America/New_York')::date AS business_date,

    COUNT(DISTINCT device_id)                             AS active_devices,
    COUNT(DISTINCT device_id) FILTER (WHERE engaged)      AS engaged_devices,
    COUNT(*)                                              AS total_events,
    AVG(rssi)                                             AS avg_rssi,

    -- A row counts as an error_event only if any element in the
    -- error_codes_json array is non-zero. Venom controllers send one
    -- code slot per probe (commonly [0,0,0,0,0]); the previous filter
    -- of "!= '[]' AND != '[0]'" treated every multi-probe all-OK row
    -- as an error, producing a misleading near-total error rate.
    COUNT(*) FILTER (
        WHERE EXISTS (
            SELECT 1 FROM jsonb_array_elements(error_codes_json) AS elem
            WHERE (elem)::text::int <> 0
        )
    )                                                     AS error_events,

    AVG(target_temp) FILTER (WHERE target_temp IS NOT NULL AND target_temp > 0)
                                                          AS avg_cook_temp
FROM telemetry_stream_events
WHERE sample_timestamp IS NOT NULL
  AND sample_timestamp >= %(cutoff)s
GROUP BY 1
ORDER BY 1;
"""

FIRMWARE_DISTRIBUTION_SQL = """\
SELECT
    (sample_timestamp AT TIME ZONE 'America/New_York')::date AS business_date,
    COALESCE(firmware_version, 'unknown')        AS fw,
    COUNT(*)                                     AS device_count
FROM telemetry_stream_events
WHERE sample_timestamp IS NOT NULL
  AND sample_timestamp >= %(cutoff)s
GROUP BY 1, 2
ORDER BY 1, 3 DESC;
"""

MODEL_DISTRIBUTION_SQL = """\
SELECT
    (sample_timestamp AT TIME ZONE 'America/New_York')::date AS business_date,
    COALESCE(grill_type, 'unknown')              AS model,
    COUNT(*)                                     AS device_count
FROM telemetry_stream_events
WHERE sample_timestamp IS NOT NULL
  AND sample_timestamp >= %(cutoff)s
GROUP BY 1, 2
ORDER BY 1, 3 DESC;
"""

# Per (day, device) event count — used to build the pre-classified
# product-family distribution. Each event attributes to the device's
# most-recently-observed product family. The family is resolved ONCE
# per device (build_device_family_map below), so this query stays cheap.
DEVICE_EVENT_COUNTS_SQL = """\
SELECT
    (sample_timestamp AT TIME ZONE 'America/New_York')::date AS business_date,
    device_id,
    COUNT(*)                                                 AS event_count
FROM telemetry_stream_events
WHERE sample_timestamp IS NOT NULL
  AND sample_timestamp >= %(cutoff)s
  AND device_id IS NOT NULL
GROUP BY 1, 2;
"""

# Latest per-device signals, fleetwide. We classify *current* product
# family and assume the factory-wired shadow value is stable across
# OTAs — so using today's classification for a historical event is
# correct (the grill was always a Huntsman or always a Kettle; it
# didn't change physical hardware).
DEVICE_SIGNALS_SQL = """\
SELECT DISTINCT ON (device_id)
    device_id,
    grill_type,
    firmware_version,
    (raw_payload->'device_data'->'reported'->'heat'->'t2'->>'max')::int AS t2_max
FROM telemetry_stream_events
WHERE device_id IS NOT NULL
ORDER BY device_id, sample_timestamp DESC;
"""

# Any device that has EVER reported a Huntsman V1 firmware in
# telemetry_stream_events OR telemetry_sessions. Used as the
# firmware-history fallback when the shadow t2_max is unavailable.
HUNTSMAN_HISTORY_SQL = """\
SELECT DISTINCT device_id FROM telemetry_stream_events
WHERE device_id IS NOT NULL
  AND firmware_version IN ('01.01.33')
UNION
SELECT DISTINCT device_id FROM telemetry_sessions
WHERE device_id IS NOT NULL
  AND firmware_version IN ('01.01.33');
"""

# Firmware alpha/beta test cohort device ids — latest firmware in the
# 01.01.9x band. These devices are held out of the default
# product_family_distribution (they're running experimental firmware,
# so including them would skew general-fleet metrics). A second pass
# includes them for the Firmware Hub.
TEST_COHORT_SQL = """\
SELECT DISTINCT device_id FROM (
  SELECT DISTINCT ON (device_id) device_id, firmware_version
  FROM telemetry_stream_events
  WHERE device_id IS NOT NULL
  ORDER BY device_id, sample_timestamp DESC
) t
WHERE firmware_version ~ '^01\\.01\\.9[0-9]$';
"""

PEAK_HOUR_SQL = """\
SELECT
    (sample_timestamp AT TIME ZONE 'UTC')::date                   AS business_date,
    EXTRACT(HOUR FROM sample_timestamp AT TIME ZONE 'America/New_York')::int   AS hour,
    COUNT(*)                                                       AS event_count
FROM telemetry_stream_events
WHERE sample_timestamp IS NOT NULL
  AND sample_timestamp >= %(cutoff)s
GROUP BY 1, 2
ORDER BY 1, 2;
"""

SESSION_EVENTS_SQL = """\
SELECT
    device_id,
    sample_timestamp,
    created_at,
    current_temp,
    target_temp,
    rssi,
    firmware_version,
    grill_type,
    engaged,
    error_codes_json
FROM telemetry_stream_events
WHERE sample_timestamp IS NOT NULL
  AND (sample_timestamp AT TIME ZONE 'America/New_York')::date = %(day)s
ORDER BY device_id, sample_timestamp;
"""

# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------

UPSERT_SQL = """\
INSERT INTO telemetry_history_daily (
    business_date,
    active_devices,
    engaged_devices,
    total_events,
    avg_rssi,
    error_events,
    firmware_distribution,
    model_distribution,
    product_family_distribution,
    avg_cook_temp,
    peak_hour_distribution,
    session_count,
    successful_sessions,
    cook_styles_json,
    cook_style_details_json,
    temp_range_json,
    duration_range_json,
    unique_devices_seen,
    source,
    created_at,
    updated_at
) VALUES (
    %(business_date)s,
    %(active_devices)s,
    %(engaged_devices)s,
    %(total_events)s,
    %(avg_rssi)s,
    %(error_events)s,
    %(firmware_distribution)s,
    %(model_distribution)s,
    %(product_family_distribution)s,
    %(avg_cook_temp)s,
    %(peak_hour_distribution)s,
    %(session_count)s,
    %(successful_sessions)s,
    %(cook_styles_json)s,
    %(cook_style_details_json)s,
    %(temp_range_json)s,
    %(duration_range_json)s,
    %(unique_devices_seen)s,
    'stream_materialized',
    NOW(),
    NOW()
)
ON CONFLICT (business_date) DO UPDATE SET
    active_devices              = EXCLUDED.active_devices,
    engaged_devices             = EXCLUDED.engaged_devices,
    total_events                = EXCLUDED.total_events,
    avg_rssi                    = EXCLUDED.avg_rssi,
    error_events                = EXCLUDED.error_events,
    firmware_distribution       = EXCLUDED.firmware_distribution,
    model_distribution          = EXCLUDED.model_distribution,
    product_family_distribution = EXCLUDED.product_family_distribution,
    avg_cook_temp               = EXCLUDED.avg_cook_temp,
    peak_hour_distribution      = EXCLUDED.peak_hour_distribution,
    session_count               = EXCLUDED.session_count,
    successful_sessions         = EXCLUDED.successful_sessions,
    cook_styles_json            = EXCLUDED.cook_styles_json,
    cook_style_details_json     = EXCLUDED.cook_style_details_json,
    temp_range_json             = EXCLUDED.temp_range_json,
    duration_range_json         = EXCLUDED.duration_range_json,
    unique_devices_seen         = EXCLUDED.unique_devices_seen,
    source                      = 'stream_materialized',
    updated_at                  = NOW()
WHERE
    %(force)s
    OR telemetry_history_daily.total_events < EXCLUDED.total_events;
"""


def build_device_family_map(cur) -> tuple[dict[str, str], set[str]]:
    """Resolve each device_id to its product family once. Returns
    ``(device_family_map, test_cohort_ids)``. The map covers every
    device that has ever appeared in telemetry_stream_events, and
    classifies using the full product_taxonomy pipeline (t2_max →
    firmware history → current firmware). The returned test_cohort_ids
    set lets the caller optionally hold alpha/beta testers out of the
    general-fleet distribution.
    """
    cur.execute(HUNTSMAN_HISTORY_SQL)
    huntsman_ids = {row["device_id"] for row in cur.fetchall() if row["device_id"]}

    cur.execute(TEST_COHORT_SQL)
    test_cohort_ids = {row["device_id"] for row in cur.fetchall() if row["device_id"]}

    cur.execute(DEVICE_SIGNALS_SQL)
    family_map: dict[str, str] = {}
    for row in cur.fetchall():
        did = row["device_id"]
        if not did:
            continue
        family = classify_product(
            row["grill_type"],
            row["firmware_version"],
            device_id=did,
            huntsman_device_ids=huntsman_ids,
            t2_max=row["t2_max"],
        )
        family_map[did] = family
    return family_map, test_cohort_ids


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _build_distribution(rows: list[dict], date_key: str, value_key: str, label_key: str) -> dict[date, dict[str, int]]:
    """Group distribution rows into {business_date: {label: count}}."""
    result: dict[date, dict[str, int]] = {}
    for row in rows:
        bd = row[date_key]
        result.setdefault(bd, {})[row[label_key]] = row["device_count"]
    return result


def _build_peak_hours(rows: list[dict]) -> dict[date, dict[str, int]]:
    """Group peak-hour rows into {business_date: {"HH": count}}."""
    result: dict[date, dict[str, int]] = {}
    for row in rows:
        bd = row["business_date"]
        hour_label = f"{int(row['hour']):02d}"
        result.setdefault(bd, {})[hour_label] = row["event_count"]
    return result


def backfill_legacy_product_family(conn, family_map: dict[str, str], test_cohort_ids: set[str]) -> int:
    """Populate ``product_family_distribution`` on rows that pre-date
    the stream-events table (``source='ddb_export_backfill_v2'``) by
    re-keying each raw ``model_distribution`` entry through the
    product-taxonomy classifier.

    Approximation for the V1 JOEHY lumped bucket: ``W:K:22:1:V`` events
    are split between Huntsman and Weber Kettle using the **current**
    fleet-wide ratio (per the shadow heat.t2.max audit). This is
    necessary because historical per-device shadow data is not
    available, but the factory-wired hardware range is stable over
    time — so today's Huntsman:Kettle ratio is a reasonable proxy for
    how historical W:K:22:1:V events should have split.
    """
    # Build the current fleet-wide Huntsman/Weber-Kettle ratio from
    # the device_family_map. Only JOEHY V1 devices count; V2 devices
    # already report their family directly in grill_type so don't
    # feed into the ratio.
    joehy_families = [f for did, f in family_map.items() if f in ("Huntsman", "Kettle")]
    total_joehy = len(joehy_families) or 1
    huntsman_ratio = joehy_families.count("Huntsman") / total_joehy
    print(
        f"  V1 JOEHY fleet-wide ratio for legacy backfill: "
        f"{huntsman_ratio:.2%} Huntsman / {(1 - huntsman_ratio):.2%} Weber Kettle "
        f"(n={total_joehy} devices with t2_max signal)"
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, business_date, model_distribution
            FROM telemetry_history_daily
            WHERE COALESCE(product_family_distribution, '{}'::jsonb) = '{}'::jsonb
            ORDER BY business_date
            """
        )
        rows = cur.fetchall()

    if not rows:
        print("  No rows need legacy backfill.")
        return 0

    updates = 0
    with conn.cursor() as cur:
        for r in rows:
            md = r["model_distribution"] or {}
            family_counts: dict[str, int] = {}
            for raw_model, count in md.items():
                count = int(count or 0)
                if count == 0:
                    continue
                if not raw_model or raw_model in ("unknown", "kettle_22", "C:G:XT:1:D"):
                    family = FAMILY_UNKNOWN
                    family_counts[family] = family_counts.get(family, 0) + count
                    continue
                lower = raw_model.lower()
                if lower == "huntsman":
                    family = "Huntsman"
                elif lower in ("giant huntsman", "giant_huntsman"):
                    family = "Huntsman"  # consolidated for now
                elif lower in ("kettle", "kettle22"):
                    family = "Kettle"
                elif raw_model == JOEHY_MODEL:
                    # Split using current fleet ratio.
                    hunts = round(count * huntsman_ratio)
                    kettle = count - hunts
                    family_counts["Huntsman"] = family_counts.get("Huntsman", 0) + hunts
                    family_counts["Kettle"] = family_counts.get("Kettle", 0) + kettle
                    continue
                else:
                    family = FAMILY_UNKNOWN
                family_counts[family] = family_counts.get(family, 0) + count

            cur.execute(
                "UPDATE telemetry_history_daily SET product_family_distribution = %s, updated_at = NOW() WHERE id = %s",
                (json.dumps(family_counts), r["id"]),
            )
            updates += cur.rowcount

    conn.commit()
    return updates


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Materialize daily aggregates from telemetry_stream_events into telemetry_history_daily.",
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=7,
        help="Number of days to look back (default: 7).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite existing rows even if they contain more events (e.g. from S3 backfill).",
    )
    parser.add_argument(
        "--backfill-legacy-families",
        action="store_true",
        default=False,
        help=(
            "Also populate product_family_distribution on rows that predate the "
            "stream-events table, by reclassifying the existing model_distribution "
            "using the current fleet-wide Huntsman:Kettle ratio for W:K:22:1:V."
        ),
    )
    args = parser.parse_args()

    _load_dotenv(ENV_PATH)
    dsn = _dsn_from_env()

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days_back)
    params = {"cutoff": cutoff}

    print(f"Materializing telemetry_history_daily for the last {args.days_back} day(s) (cutoff={cutoff.date()}).")
    if args.force:
        print("  --force enabled: will overwrite even if existing row has more events.")

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        # ------- Fetch aggregates in parallel-safe sequential queries -------
        with conn.cursor() as cur:
            cur.execute(AGGREGATE_SQL, params)
            agg_rows = cur.fetchall()

            cur.execute(FIRMWARE_DISTRIBUTION_SQL, params)
            fw_rows = cur.fetchall()

            cur.execute(MODEL_DISTRIBUTION_SQL, params)
            model_rows = cur.fetchall()

            cur.execute(PEAK_HOUR_SQL, params)
            peak_rows = cur.fetchall()

            # Per-device event counts per day — paired with the
            # device→family map to build product_family_distribution.
            cur.execute(DEVICE_EVENT_COUNTS_SQL, params)
            device_event_rows = cur.fetchall()

            print("Resolving device→product family classification (fleetwide).")
            device_family_map, test_cohort_ids = build_device_family_map(cur)
            print(
                f"  {len(device_family_map)} devices classified,"
                f" {len(test_cohort_ids)} held out of the general-fleet distribution as alpha/beta testers."
            )

        if not agg_rows:
            print("No stream events found in the requested window. Nothing to materialize.")
            return 0

        fw_dist = _build_distribution(fw_rows, "business_date", "device_count", "fw")
        model_dist = _build_distribution(model_rows, "business_date", "device_count", "model")
        peak_hours = _build_peak_hours(peak_rows)

        # Build product_family_distribution = {family: event_count} per
        # day. Testers are held out; unclassified devices (no shadow
        # and no firmware history) fall into "Unknown" so bad data
        # stays visible in the UI.
        family_dist: dict[date, dict[str, int]] = {}
        for row in device_event_rows:
            did = row["device_id"]
            if did in test_cohort_ids:
                continue
            family = device_family_map.get(did, FAMILY_UNKNOWN)
            bd = row["business_date"]
            family_dist.setdefault(bd, {})[family] = (
                family_dist.setdefault(bd, {}).get(family, 0) + int(row["event_count"] or 0)
            )

        # ------- Upsert each day -------
        upserted = 0
        skipped = 0

        with conn.cursor() as cur:
            for row in agg_rows:
                bd = row["business_date"]

                # Derive cook sessions for this day
                cur.execute(SESSION_EVENTS_SQL, {"day": bd})
                raw_events = cur.fetchall()
                device_events: dict[str, list[EventRow]] = {}
                device_ids: set[str] = set()
                for ev in raw_events:
                    did = ev["device_id"]
                    device_ids.add(did)
                    device_events.setdefault(did, []).append(EventRow(
                        device_id=did,
                        sample_timestamp=ev["sample_timestamp"],
                        created_at=ev["created_at"],
                        current_temp=float(ev["current_temp"]) if ev["current_temp"] is not None else None,
                        target_temp=float(ev["target_temp"]) if ev["target_temp"] is not None else None,
                        rssi=float(ev["rssi"]) if ev["rssi"] is not None else None,
                        firmware_version=ev["firmware_version"],
                        grill_type=ev["grill_type"],
                        engaged=bool(ev["engaged"]),
                        error_codes_json=ev["error_codes_json"] or [],
                    ))
                all_sessions = []
                for did, events in device_events.items():
                    all_sessions.extend(derive_sessions_from_rows(did, events))
                cook_cols = build_daily_cook_columns(all_sessions, device_ids)

                upsert_params = {
                    "business_date": bd,
                    "active_devices": row["active_devices"],
                    "engaged_devices": row["engaged_devices"],
                    "total_events": row["total_events"],
                    "avg_rssi": round(float(row["avg_rssi"]), 2) if row["avg_rssi"] is not None else None,
                    "error_events": row["error_events"],
                    "firmware_distribution": json.dumps(fw_dist.get(bd, {})),
                    "model_distribution": json.dumps(model_dist.get(bd, {})),
                    "product_family_distribution": json.dumps(family_dist.get(bd, {})),
                    "avg_cook_temp": round(float(row["avg_cook_temp"]), 2) if row["avg_cook_temp"] is not None else None,
                    "peak_hour_distribution": json.dumps(peak_hours.get(bd, {})),
                    "session_count": cook_cols["session_count"],
                    "successful_sessions": cook_cols["successful_sessions"],
                    "cook_styles_json": json.dumps(cook_cols["cook_styles_json"]),
                    "cook_style_details_json": json.dumps(cook_cols["cook_style_details_json"]),
                    "temp_range_json": json.dumps(cook_cols["temp_range_json"]),
                    "duration_range_json": json.dumps(cook_cols["duration_range_json"]),
                    "unique_devices_seen": cook_cols["unique_devices_seen"],
                    "force": args.force,
                }
                cur.execute(UPSERT_SQL, upsert_params)
                if cur.rowcount > 0:
                    upserted += 1
                    print(f"  {bd}: {cook_cols['session_count']} sessions, {len(device_ids)} devices")
                else:
                    skipped += 1

        conn.commit()

        if args.backfill_legacy_families:
            print("\nBackfilling product_family_distribution for legacy (S3-backfill) rows...")
            n = backfill_legacy_product_family(conn, device_family_map, test_cohort_ids)
            print(f"  {n} legacy row(s) populated.")

    # ------- Summary -------
    print(f"\nDone. {upserted} day(s) upserted, {skipped} day(s) skipped (existing row had more events).")
    if agg_rows:
        first_date = agg_rows[0]["business_date"]
        last_date = agg_rows[-1]["business_date"]
        print(f"  Date range: {first_date} to {last_date}")
        total_events = sum(r["total_events"] for r in agg_rows)
        total_devices = sum(r["active_devices"] for r in agg_rows)
        print(f"  Total events across window: {total_events:,}")
        print(f"  Total device-days across window: {total_devices:,}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
