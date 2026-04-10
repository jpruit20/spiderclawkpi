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
    (sample_timestamp AT TIME ZONE 'UTC')::date          AS business_date,

    COUNT(DISTINCT device_id)                             AS active_devices,
    COUNT(DISTINCT device_id) FILTER (WHERE engaged)      AS engaged_devices,
    COUNT(*)                                              AS total_events,
    AVG(rssi)                                             AS avg_rssi,

    COUNT(*) FILTER (
        WHERE error_codes_json != '[]'::jsonb
          AND error_codes_json != '[0]'::jsonb
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
    (sample_timestamp AT TIME ZONE 'UTC')::date AS business_date,
    COALESCE(firmware_version, 'unknown')        AS fw,
    COUNT(DISTINCT device_id)                    AS device_count
FROM telemetry_stream_events
WHERE sample_timestamp IS NOT NULL
  AND sample_timestamp >= %(cutoff)s
GROUP BY 1, 2
ORDER BY 1, 3 DESC;
"""

MODEL_DISTRIBUTION_SQL = """\
SELECT
    (sample_timestamp AT TIME ZONE 'UTC')::date AS business_date,
    COALESCE(grill_type, 'unknown')              AS model,
    COUNT(DISTINCT device_id)                    AS device_count
FROM telemetry_stream_events
WHERE sample_timestamp IS NOT NULL
  AND sample_timestamp >= %(cutoff)s
GROUP BY 1, 2
ORDER BY 1, 3 DESC;
"""

PEAK_HOUR_SQL = """\
SELECT
    (sample_timestamp AT TIME ZONE 'UTC')::date                   AS business_date,
    EXTRACT(HOUR FROM sample_timestamp AT TIME ZONE 'UTC')::int   AS hour,
    COUNT(*)                                                       AS event_count
FROM telemetry_stream_events
WHERE sample_timestamp IS NOT NULL
  AND sample_timestamp >= %(cutoff)s
GROUP BY 1, 2
ORDER BY 1, 2;
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
    avg_cook_temp,
    peak_hour_distribution,
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
    %(avg_cook_temp)s,
    %(peak_hour_distribution)s,
    'stream_materialized',
    NOW(),
    NOW()
)
ON CONFLICT (business_date) DO UPDATE SET
    active_devices         = EXCLUDED.active_devices,
    engaged_devices        = EXCLUDED.engaged_devices,
    total_events           = EXCLUDED.total_events,
    avg_rssi               = EXCLUDED.avg_rssi,
    error_events           = EXCLUDED.error_events,
    firmware_distribution  = EXCLUDED.firmware_distribution,
    model_distribution     = EXCLUDED.model_distribution,
    avg_cook_temp          = EXCLUDED.avg_cook_temp,
    peak_hour_distribution = EXCLUDED.peak_hour_distribution,
    source                 = 'stream_materialized',
    updated_at             = NOW()
WHERE
    %(force)s
    OR telemetry_history_daily.total_events < EXCLUDED.total_events;
"""


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

        if not agg_rows:
            print("No stream events found in the requested window. Nothing to materialize.")
            return 0

        fw_dist = _build_distribution(fw_rows, "business_date", "device_count", "fw")
        model_dist = _build_distribution(model_rows, "business_date", "device_count", "model")
        peak_hours = _build_peak_hours(peak_rows)

        # ------- Upsert each day -------
        upserted = 0
        skipped = 0

        with conn.cursor() as cur:
            for row in agg_rows:
                bd = row["business_date"]
                upsert_params = {
                    "business_date": bd,
                    "active_devices": row["active_devices"],
                    "engaged_devices": row["engaged_devices"],
                    "total_events": row["total_events"],
                    "avg_rssi": round(float(row["avg_rssi"]), 2) if row["avg_rssi"] is not None else None,
                    "error_events": row["error_events"],
                    "firmware_distribution": json.dumps(fw_dist.get(bd, {})),
                    "model_distribution": json.dumps(model_dist.get(bd, {})),
                    "avg_cook_temp": round(float(row["avg_cook_temp"]), 2) if row["avg_cook_temp"] is not None else None,
                    "peak_hour_distribution": json.dumps(peak_hours.get(bd, {})),
                    "force": args.force,
                }
                cur.execute(UPSERT_SQL, upsert_params)
                if cur.rowcount > 0:
                    upserted += 1
                else:
                    skipped += 1

        conn.commit()

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
