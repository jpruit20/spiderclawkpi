#!/usr/bin/env python3
"""
Import DynamoDB S3 export into telemetry_history_daily aggregates.

Streams gzipped JSONL files from S3 one at a time, computes daily aggregates,
and upserts them into the KPI PostgreSQL database.

Usage:
    python scripts/import_s3_history.py
    python scripts/import_s3_history.py --dry-run
    python scripts/import_s3_history.py --start-date 2024-06-01 --end-date 2024-12-31
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator

# Allow imports from backend/app
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.cook_classification import EventRow, derive_sessions_from_rows, build_daily_cook_columns

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

S3_BUCKET = "spider-kpi-telemetry-export"
S3_PREFIX = "spider-kpi/sg_device_shadows-export-2026-04-09/"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
BATCH_SIZE = 500  # rows per DB commit
PROGRESS_INTERVAL = 1  # print progress every N files
DEFAULT_START_DATE = date(2024, 1, 1)

logger = logging.getLogger("import_s3_history")


# ---------------------------------------------------------------------------
# .env loader (no third-party dependency)
# ---------------------------------------------------------------------------

def load_env(env_path: Path) -> dict[str, str]:
    """Parse a .env file and inject variables into os.environ.

    Handles quoted values (single and double), inline comments, and
    multi-line values enclosed in double quotes with literal \\n escapes.
    """
    env_vars: dict[str, str] = {}
    if not env_path.is_file():
        logger.warning(".env file not found at %s", env_path)
        return env_vars

    with env_path.open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()

            # Strip surrounding quotes
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]

            env_vars[key] = value
            os.environ.setdefault(key, value)

    return env_vars


# ---------------------------------------------------------------------------
# DynamoDB JSON deserialization
# ---------------------------------------------------------------------------

DDB_TYPE_KEYS = {"S", "N", "BOOL", "NULL", "M", "L", "SS", "NS", "BS", "B"}


def _deserialize(value: Any) -> Any:
    """Recursively convert DynamoDB JSON attribute to native Python."""
    if not isinstance(value, dict) or len(value) != 1:
        return value
    type_key, payload = next(iter(value.items()))
    if type_key == "S":
        return payload
    if type_key == "N":
        return float(payload) if "." in str(payload) else int(payload)
    if type_key == "BOOL":
        return bool(payload)
    if type_key == "NULL":
        return None
    if type_key == "M":
        return {k: _deserialize(v) for k, v in payload.items()}
    if type_key == "L":
        return [_deserialize(v) for v in payload]
    if type_key in ("SS", "NS", "BS"):
        return payload  # return as list
    if type_key == "B":
        return payload
    return value


def normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    """If every top-level value looks like a DynamoDB typed attribute, unwrap it."""
    if all(
        isinstance(v, dict) and len(v) == 1 and next(iter(v.keys())) in DDB_TYPE_KEYS
        for v in item.values()
    ):
        return {k: _deserialize(v) for k, v in item.items()}
    return item


# ---------------------------------------------------------------------------
# Epoch millis -> datetime
# ---------------------------------------------------------------------------

def epoch_ms_to_datetime(value: Any) -> datetime | None:
    try:
        raw = int(value)
    except (TypeError, ValueError):
        return None
    if raw <= 0:
        return None
    # Distinguish seconds vs milliseconds
    if raw > 1e12:
        return datetime.fromtimestamp(raw / 1000.0, tz=timezone.utc)
    return datetime.fromtimestamp(raw, tz=timezone.utc)


# ---------------------------------------------------------------------------
# Daily aggregate accumulator
# ---------------------------------------------------------------------------

@dataclass
class DailyBucket:
    active_device_ids: set[str] = field(default_factory=set)
    engaged_device_ids: set[str] = field(default_factory=set)
    total_events: int = 0
    rssi_sum: float = 0.0
    rssi_count: int = 0
    error_events: int = 0
    firmware_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    model_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    cook_temp_sum: float = 0.0
    cook_temp_count: int = 0
    hour_counts: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    session_events: list[EventRow] = field(default_factory=list)


# ---------------------------------------------------------------------------
# S3 streaming helpers
# ---------------------------------------------------------------------------

def get_s3_client():
    """Create a boto3 S3 client using env credentials."""
    import boto3

    return boto3.client(
        "s3",
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        region_name=os.environ.get("AWS_REGION", "us-east-2"),
    )


def list_export_files(s3_client, bucket: str, prefix: str) -> list[str]:
    """List all .json.gz files under the export prefix."""
    keys: list[str] = []
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".json.gz") or key.endswith(".gz"):
                keys.append(key)
    keys.sort()
    logger.info("Found %d gzipped files in s3://%s/%s", len(keys), bucket, prefix)
    return keys


def stream_records_from_s3_file(
    s3_client,
    bucket: str,
    key: str,
) -> Iterator[dict[str, Any]]:
    """Download one gzipped JSONL file from S3 and yield deserialized records."""
    response = s3_client.get_object(Bucket=bucket, Key=key)
    body = response["Body"]

    with gzip.open(body, mode="rt", encoding="utf-8") as gz:
        for line in gz:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(parsed, dict):
                continue
            item = parsed.get("Item") if isinstance(parsed.get("Item"), dict) else parsed
            if isinstance(item, dict):
                yield normalize_item(item)


# ---------------------------------------------------------------------------
# Record processing
# ---------------------------------------------------------------------------

def process_record(
    record: dict[str, Any],
    buckets: dict[str, DailyBucket],
    start_date: date,
    end_date: date | None,
) -> bool:
    """Extract fields from one DynamoDB record and accumulate into daily buckets.

    Returns True if the record was counted, False if skipped.
    """
    device_id = str(record.get("device_id") or "").strip()
    sample_dt = epoch_ms_to_datetime(record.get("sample_time"))

    if not device_id or not sample_dt:
        return False

    record_date = sample_dt.date()
    if record_date < start_date:
        return False
    if end_date and record_date > end_date:
        return False

    date_key = record_date.isoformat()
    bucket = buckets[date_key]

    bucket.active_device_ids.add(device_id)
    bucket.total_events += 1
    bucket.hour_counts[sample_dt.hour] += 1

    # Navigate into device_data.reported
    device_data = record.get("device_data")
    reported: dict[str, Any] = {}
    if isinstance(device_data, dict):
        reported = device_data.get("reported") or {}
        if not isinstance(reported, dict):
            reported = {}

    # Engaged
    engaged = reported.get("engaged")
    if engaged is True or engaged == 1:
        bucket.engaged_device_ids.add(device_id)

    # Firmware
    firmware = str(reported.get("vers") or "").strip()
    if firmware:
        bucket.firmware_counts[firmware] += 1

    # Model
    model = str(reported.get("model") or "").strip()
    if model:
        bucket.model_counts[model] += 1

    # RSSI
    rssi_raw = reported.get("RSSI")
    rssi_val: float | None = None
    if rssi_raw is not None:
        try:
            rssi_val = float(rssi_raw)
            bucket.rssi_sum += rssi_val
            bucket.rssi_count += 1
        except (TypeError, ValueError):
            pass

    # Target cook temperature (heat.t2.trgt)
    heat = reported.get("heat")
    if isinstance(heat, dict):
        t2 = heat.get("t2")
        if isinstance(t2, dict):
            trgt_raw = t2.get("trgt")
            if trgt_raw is not None:
                try:
                    trgt_val = float(trgt_raw)
                    if trgt_val > 0:
                        bucket.cook_temp_sum += trgt_val
                        bucket.cook_temp_count += 1
                except (TypeError, ValueError):
                    pass

    # Errors
    errors = reported.get("errors")
    error_list = []
    if isinstance(errors, list) and len(errors) > 0:
        error_list = [e for e in errors if e not in (None, False)]
        if any(e != 0 for e in error_list):
            bucket.error_events += 1

    # Accumulate EventRow for session derivation
    current_temp_raw = reported.get("mainTemp")
    current_temp = None
    if current_temp_raw is not None:
        try:
            current_temp = float(current_temp_raw)
        except (TypeError, ValueError):
            pass

    target_temp = None
    if isinstance(heat, dict):
        t2 = heat.get("t2")
        if isinstance(t2, dict):
            try:
                target_temp = float(t2.get("trgt") or 0) or None
            except (TypeError, ValueError):
                pass

    bucket.session_events.append(EventRow(
        device_id=device_id,
        sample_timestamp=sample_dt,
        created_at=sample_dt,
        current_temp=current_temp,
        target_temp=target_temp,
        rssi=rssi_val,
        firmware_version=firmware or None,
        grill_type=model or None,
        engaged=engaged is True or engaged == 1,
        error_codes_json=error_list,
    ))

    return True


# ---------------------------------------------------------------------------
# Database writer
# ---------------------------------------------------------------------------

def get_db_url() -> str:
    """Return a psycopg-compatible connection string from DATABASE_URL.

    The .env file may contain an SQLAlchemy-style URL like
    ``postgresql+psycopg://...`` which psycopg cannot parse directly.
    """
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        raise RuntimeError("DATABASE_URL not set in environment or .env")

    # Strip SQLAlchemy dialect prefix
    for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://", "postgresql+asyncpg://"):
        if raw.startswith(prefix):
            return "postgresql://" + raw[len(prefix):]
    return raw


def write_to_database(buckets: dict[str, DailyBucket], cook_columns: dict[str, dict[str, Any]]) -> int:
    """Upsert daily aggregates into telemetry_history_daily.

    Returns the number of rows upserted.
    """
    import psycopg

    dsn = get_db_url()
    logger.info("Connecting to database ...")

    upsert_sql = """
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
            session_count,
            successful_sessions,
            cook_styles_json,
            cook_style_details_json,
            temp_range_json,
            duration_range_json,
            unique_devices_seen,
            source,
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
            %(session_count)s,
            %(successful_sessions)s,
            %(cook_styles_json)s,
            %(cook_style_details_json)s,
            %(temp_range_json)s,
            %(duration_range_json)s,
            %(unique_devices_seen)s,
            %(source)s,
            NOW()
        )
        ON CONFLICT (business_date) DO UPDATE SET
            active_devices          = EXCLUDED.active_devices,
            engaged_devices         = EXCLUDED.engaged_devices,
            total_events            = EXCLUDED.total_events,
            avg_rssi                = EXCLUDED.avg_rssi,
            error_events            = EXCLUDED.error_events,
            firmware_distribution   = EXCLUDED.firmware_distribution,
            model_distribution      = EXCLUDED.model_distribution,
            avg_cook_temp           = EXCLUDED.avg_cook_temp,
            peak_hour_distribution  = EXCLUDED.peak_hour_distribution,
            session_count           = EXCLUDED.session_count,
            successful_sessions     = EXCLUDED.successful_sessions,
            cook_styles_json        = EXCLUDED.cook_styles_json,
            cook_style_details_json = EXCLUDED.cook_style_details_json,
            temp_range_json         = EXCLUDED.temp_range_json,
            duration_range_json     = EXCLUDED.duration_range_json,
            unique_devices_seen     = EXCLUDED.unique_devices_seen,
            source                  = EXCLUDED.source,
            updated_at              = NOW()
    """

    rows_written = 0
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            sorted_dates = sorted(buckets.keys())
            batch: list[dict[str, Any]] = []

            for date_key in sorted_dates:
                b = buckets[date_key]
                cc = cook_columns.get(date_key, {})
                row = {
                    "business_date": date_key,
                    "active_devices": len(b.active_device_ids),
                    "engaged_devices": len(b.engaged_device_ids),
                    "total_events": b.total_events,
                    "avg_rssi": round(b.rssi_sum / b.rssi_count, 2) if b.rssi_count > 0 else None,
                    "error_events": b.error_events,
                    "firmware_distribution": json.dumps(dict(b.firmware_counts), sort_keys=True),
                    "model_distribution": json.dumps(dict(b.model_counts), sort_keys=True),
                    "avg_cook_temp": round(b.cook_temp_sum / b.cook_temp_count, 2) if b.cook_temp_count > 0 else None,
                    "peak_hour_distribution": json.dumps(
                        {str(h): c for h, c in sorted(b.hour_counts.items())},
                        sort_keys=True,
                    ),
                    "session_count": cc.get("session_count"),
                    "successful_sessions": cc.get("successful_sessions"),
                    "cook_styles_json": json.dumps(cc.get("cook_styles_json", {})),
                    "cook_style_details_json": json.dumps(cc.get("cook_style_details_json", {})),
                    "temp_range_json": json.dumps(cc.get("temp_range_json", {})),
                    "duration_range_json": json.dumps(cc.get("duration_range_json", {})),
                    "unique_devices_seen": cc.get("unique_devices_seen") or len(b.active_device_ids),
                    "source": "ddb_export_backfill",
                }
                batch.append(row)

                if len(batch) >= BATCH_SIZE:
                    cur.executemany(upsert_sql, batch)
                    conn.commit()
                    rows_written += len(batch)
                    logger.info("Committed batch of %d rows (total: %d)", len(batch), rows_written)
                    batch.clear()

            if batch:
                cur.executemany(upsert_sql, batch)
                conn.commit()
                rows_written += len(batch)
                logger.info("Committed final batch of %d rows (total: %d)", len(batch), rows_written)

    return rows_written


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def print_summary(buckets: dict[str, DailyBucket]) -> None:
    sorted_dates = sorted(buckets.keys())
    if not sorted_dates:
        logger.info("No data collected.")
        return

    total_events = sum(b.total_events for b in buckets.values())
    total_active = set()
    total_engaged = set()
    for b in buckets.values():
        total_active.update(b.active_device_ids)
        total_engaged.update(b.engaged_device_ids)

    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    logger.info("Date range       : %s to %s", sorted_dates[0], sorted_dates[-1])
    logger.info("Days with data   : %d", len(sorted_dates))
    logger.info("Total events     : %s", f"{total_events:,}")
    logger.info("Distinct devices : %s", f"{len(total_active):,}")
    logger.info("Engaged devices  : %s", f"{len(total_engaged):,}")

    # Top 5 days by event count
    top_days = sorted(buckets.items(), key=lambda x: x[1].total_events, reverse=True)[:5]
    logger.info("Top 5 days by event count:")
    for d, b in top_days:
        logger.info(
            "  %s  events=%s  active=%d  engaged=%d",
            d,
            f"{b.total_events:,}",
            len(b.active_device_ids),
            len(b.engaged_device_ids),
        )
    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_date(value: str) -> date:
    """Parse YYYY-MM-DD date string."""
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date format: {value!r}. Use YYYY-MM-DD.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import DynamoDB S3 export into telemetry_history_daily aggregates.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Process files and print stats but do not write to the database.",
    )
    parser.add_argument(
        "--start-date",
        type=parse_date,
        default=DEFAULT_START_DATE,
        help="Only include records on or after this date (YYYY-MM-DD). Default: 2024-01-01",
    )
    parser.add_argument(
        "--end-date",
        type=parse_date,
        default=None,
        help="Only include records on or before this date (YYYY-MM-DD). Default: no limit",
    )
    parser.add_argument(
        "--bucket",
        default=S3_BUCKET,
        help=f"S3 bucket name. Default: {S3_BUCKET}",
    )
    parser.add_argument(
        "--prefix",
        default=S3_PREFIX,
        help=f"S3 key prefix for the export. Default: {S3_PREFIX}",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=ENV_FILE,
        help=f"Path to .env file. Default: {ENV_FILE}",
    )
    args = parser.parse_args()

    # ---- Logging ----------------------------------------------------------
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # ---- Environment ------------------------------------------------------
    logger.info("Loading environment from %s", args.env_file)
    load_env(args.env_file)

    logger.info("Start date filter : %s", args.start_date.isoformat())
    logger.info("End date filter   : %s", args.end_date.isoformat() if args.end_date else "(none)")
    if args.dry_run:
        logger.info("*** DRY RUN MODE -- no database writes ***")

    # ---- S3 listing -------------------------------------------------------
    s3 = get_s3_client()
    file_keys = list_export_files(s3, args.bucket, args.prefix)
    if not file_keys:
        logger.error("No export files found at s3://%s/%s", args.bucket, args.prefix)
        return 1

    # ---- Processing -------------------------------------------------------
    buckets: dict[str, DailyBucket] = defaultdict(DailyBucket)
    total_records = 0
    total_matched = 0
    total_errors = 0
    t_start = time.monotonic()

    for file_idx, key in enumerate(file_keys, start=1):
        file_records = 0
        file_matched = 0

        try:
            for record in stream_records_from_s3_file(s3, args.bucket, key):
                file_records += 1
                if process_record(record, buckets, args.start_date, args.end_date):
                    file_matched += 1
        except Exception:
            total_errors += 1
            logger.exception("Error processing file %s", key)
            continue

        total_records += file_records
        total_matched += file_matched

        if file_idx % PROGRESS_INTERVAL == 0 or file_idx == len(file_keys):
            elapsed = time.monotonic() - t_start
            rate = total_records / elapsed if elapsed > 0 else 0
            logger.info(
                "[%d/%d files]  records=%s  matched=%s  days=%d  rate=%.0f rec/s  elapsed=%.1fs",
                file_idx,
                len(file_keys),
                f"{total_records:,}",
                f"{total_matched:,}",
                len(buckets),
                rate,
                elapsed,
            )

    elapsed_total = time.monotonic() - t_start
    logger.info(
        "Processing complete in %.1fs.  Total records: %s  Matched: %s  File errors: %d",
        elapsed_total,
        f"{total_records:,}",
        f"{total_matched:,}",
        total_errors,
    )

    # ---- Derive cook sessions per day -------------------------------------
    logger.info("Deriving cook sessions for %d days ...", len(buckets))
    cook_columns_by_date: dict[str, dict[str, Any]] = {}
    for date_key in sorted(buckets.keys()):
        b = buckets[date_key]
        if not b.session_events:
            cook_columns_by_date[date_key] = build_daily_cook_columns([], b.active_device_ids)
            continue
        device_events: dict[str, list[EventRow]] = defaultdict(list)
        for ev in b.session_events:
            device_events[ev.device_id].append(ev)
        all_sessions = []
        for did, events in device_events.items():
            all_sessions.extend(derive_sessions_from_rows(did, events))
        cook_columns_by_date[date_key] = build_daily_cook_columns(all_sessions, b.active_device_ids)
        # Free memory
        b.session_events.clear()
    logger.info("Session derivation complete.")

    # ---- Summary ----------------------------------------------------------
    print_summary(buckets)

    # ---- Database write ---------------------------------------------------
    if args.dry_run:
        logger.info("Dry run -- skipping database write. %d day-rows would be upserted.", len(buckets))
    else:
        if not buckets:
            logger.info("No data to write.")
            return 0
        try:
            rows = write_to_database(buckets, cook_columns_by_date)
            logger.info("Successfully upserted %d rows into telemetry_history_daily.", rows)
        except Exception:
            logger.exception("Database write failed.")
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
