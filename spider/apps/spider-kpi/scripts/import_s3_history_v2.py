#!/usr/bin/env python3
"""Single-pass S3 DynamoDB backfill — v2.

Why v2 exists (vs import_s3_history.py):

  * v1 re-read all 309 S3 files (3.73 GB) for every monthly chunk, taking
    ~3 hours per month and 100+ hours end-to-end. It was killed partway
    through; sessions never derived for months past 2024-03.
  * v1 accumulated every EventRow in memory across ALL days in a run — for
    wide date ranges this OOM'd on the 4 GB droplet.
  * v1 only computed daily aggregates; individual cook sessions were never
    persisted to telemetry_sessions (table had 7 rows total).

v2 design:

  * **Single pass** through every S3 file, parsing once.
  * Events are streamed to per-day JSONL temp files on disk
    (/tmp/s3_backfill/YYYY-MM-DD.jsonl.gz), not held in RAM.
  * After the S3 pass, each day's JSONL is read, events grouped by
    device, sessions derived, then BOTH:
      - daily aggregates upserted into telemetry_history_daily
      - individual sessions inserted into telemetry_sessions (idempotent
        via UNIQUE source_event_id = sha256(device_id|start_ts))
  * Crash-safe: a per-day file is only deleted after both DB writes commit.
  * Resume-safe: pass --skip-existing-sessions to skip any day that
    already has session_count > 0 (saves time on resumes after completion).

Usage:
    nohup .venv/bin/python scripts/import_s3_history_v2.py \\
      > /var/log/spider-kpi-backfill-v2.log 2>&1 &
    tail -f /var/log/spider-kpi-backfill-v2.log
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Iterator, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.cook_classification import (  # noqa: E402
    EventRow,
    LiteDerivedSession,
    build_daily_cook_columns,
    classify_cook_style,
    classify_duration_range,
    classify_temp_range,
    derive_sessions_from_rows,
)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

S3_BUCKET = "spider-kpi-telemetry-export"
S3_PREFIX = "spider-kpi/sg_device_shadows-export-2026-04-09/"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
DEFAULT_TEMP_DIR = Path("/tmp/s3_backfill")
DEFAULT_START_DATE = date(2024, 1, 1)

logger = logging.getLogger("import_s3_v2")


# ---------------------------------------------------------------------------
# .env loader
# ---------------------------------------------------------------------------

def load_env(env_path: Path) -> None:
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


# ---------------------------------------------------------------------------
# DynamoDB JSON deserialization
# ---------------------------------------------------------------------------

DDB_TYPE_KEYS = {"S", "N", "BOOL", "NULL", "M", "L", "SS", "NS", "BS", "B"}


def _deserialize(value: Any) -> Any:
    if not isinstance(value, dict) or len(value) != 1:
        return value
    tk, payload = next(iter(value.items()))
    if tk == "S": return payload
    if tk == "N":
        try:
            return float(payload) if "." in str(payload) else int(payload)
        except (TypeError, ValueError):
            return payload
    if tk == "BOOL": return bool(payload)
    if tk == "NULL": return None
    if tk == "M": return {k: _deserialize(v) for k, v in payload.items()}
    if tk == "L": return [_deserialize(v) for v in payload]
    if tk in ("SS", "NS", "BS", "B"): return payload
    return value


def normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    if all(
        isinstance(v, dict) and len(v) == 1 and next(iter(v.keys())) in DDB_TYPE_KEYS
        for v in item.values()
    ):
        return {k: _deserialize(v) for k, v in item.items()}
    return item


def epoch_ms_to_dt(value: Any) -> Optional[datetime]:
    try:
        raw = int(value)
    except (TypeError, ValueError):
        return None
    if raw <= 0:
        return None
    if raw > 1e12:
        return datetime.fromtimestamp(raw / 1000.0, tz=timezone.utc)
    return datetime.fromtimestamp(raw, tz=timezone.utc)


# ---------------------------------------------------------------------------
# Record extraction — produce a compact dict we can JSONL-write
# ---------------------------------------------------------------------------

def extract_event(record: dict[str, Any]) -> Optional[dict[str, Any]]:
    device_id = str(record.get("device_id") or "").strip()
    sample_dt = epoch_ms_to_dt(record.get("sample_time"))
    if not device_id or not sample_dt:
        return None

    device_data = record.get("device_data")
    reported: dict[str, Any] = {}
    if isinstance(device_data, dict):
        r = device_data.get("reported") or {}
        if isinstance(r, dict):
            reported = r

    # Current + target temp
    current_temp: Optional[float] = None
    if reported.get("mainTemp") is not None:
        try: current_temp = float(reported["mainTemp"])
        except (TypeError, ValueError): current_temp = None
    target_temp: Optional[float] = None
    heat = reported.get("heat")
    if isinstance(heat, dict):
        t2 = heat.get("t2")
        if isinstance(t2, dict) and t2.get("trgt") is not None:
            try:
                tt = float(t2["trgt"])
                if tt > 0: target_temp = tt
            except (TypeError, ValueError): pass

    # Fan intensity (for fan curve)
    intensity: Optional[float] = None
    if reported.get("intensity") is not None:
        try: intensity = float(reported["intensity"])
        except (TypeError, ValueError): intensity = None

    # RSSI
    rssi: Optional[float] = None
    if reported.get("RSSI") is not None:
        try: rssi = float(reported["RSSI"])
        except (TypeError, ValueError): rssi = None

    # Errors
    err = reported.get("errors")
    error_codes: list[int] = []
    if isinstance(err, list):
        for e in err:
            try:
                v = int(e)
                if v != 0: error_codes.append(v)
            except (TypeError, ValueError): pass

    engaged = reported.get("engaged")
    engaged_bool = engaged is True or engaged == 1

    firmware = str(reported.get("vers") or "").strip() or None
    grill = str(reported.get("model") or "").strip() or None

    return {
        "d": device_id,
        "t": int(sample_dt.timestamp()),  # seconds since epoch — compact
        "ct": current_temp,
        "tt": target_temp,
        "fan": intensity,
        "r": rssi,
        "f": firmware,
        "g": grill,
        "e": engaged_bool,
        "err": error_codes,
    }


# ---------------------------------------------------------------------------
# S3 streaming
# ---------------------------------------------------------------------------

def get_s3_client():
    import boto3
    return boto3.client(
        "s3",
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        region_name=os.environ.get("AWS_REGION", "us-east-2"),
    )


def list_export_files(s3, bucket: str, prefix: str) -> list[str]:
    keys: list[str] = []
    pager = s3.get_paginator("list_objects_v2")
    for page in pager.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            k = obj["Key"]
            if k.endswith(".json.gz") or k.endswith(".gz"):
                keys.append(k)
    keys.sort()
    return keys


def stream_records(s3, bucket: str, key: str) -> Iterator[dict[str, Any]]:
    resp = s3.get_object(Bucket=bucket, Key=key)
    with gzip.open(resp["Body"], mode="rt", encoding="utf-8") as gz:
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
# Phase 1: stream records → per-day gzipped JSONL temp files
# ---------------------------------------------------------------------------

class DayWriterPool:
    """Keeps a capped LRU of open per-day writers — opens and closes on demand."""

    def __init__(self, temp_dir: Path, max_open: int = 64):
        self.temp_dir = temp_dir
        self.max_open = max_open
        self._writers: dict[str, Any] = {}  # date_key -> TextIO
        self._lru: list[str] = []

    def _path(self, date_key: str) -> Path:
        return self.temp_dir / f"{date_key}.jsonl.gz"

    def write(self, date_key: str, event: dict[str, Any]) -> None:
        w = self._writers.get(date_key)
        if w is None:
            if len(self._writers) >= self.max_open:
                # Evict LRU
                victim = self._lru.pop(0)
                self._writers[victim].close()
                del self._writers[victim]
            w = gzip.open(self._path(date_key), mode="at", encoding="utf-8", compresslevel=3)
            self._writers[date_key] = w
            self._lru.append(date_key)
        else:
            try:
                self._lru.remove(date_key)
            except ValueError:
                pass
            self._lru.append(date_key)
        w.write(json.dumps(event, separators=(",", ":")) + "\n")

    def close_all(self) -> None:
        for w in self._writers.values():
            try: w.close()
            except Exception: pass
        self._writers.clear()
        self._lru.clear()

    def date_files(self) -> list[tuple[str, Path]]:
        out = []
        for p in sorted(self.temp_dir.glob("*.jsonl.gz")):
            m = re.match(r"(\d{4}-\d{2}-\d{2})", p.name)
            if m: out.append((m.group(1), p))
        return out


def phase1_extract_events(
    s3, bucket: str, prefix: str,
    start_date: date, end_date: Optional[date],
    temp_dir: Path,
    progress_every: int = 1,
) -> tuple[int, int]:
    """Stream S3 files; write events to per-day JSONL in temp_dir."""
    temp_dir.mkdir(parents=True, exist_ok=True)
    keys = list_export_files(s3, bucket, prefix)
    logger.info("Phase 1: %d S3 files to process", len(keys))

    pool = DayWriterPool(temp_dir, max_open=96)
    total_records = 0
    total_matched = 0
    t0 = time.monotonic()

    for idx, key in enumerate(keys, 1):
        file_records = 0
        file_matched = 0
        try:
            for rec in stream_records(s3, bucket, key):
                file_records += 1
                ev = extract_event(rec)
                if ev is None:
                    continue
                rec_date = datetime.fromtimestamp(ev["t"], tz=timezone.utc).date()
                if rec_date < start_date:
                    continue
                if end_date and rec_date > end_date:
                    continue
                pool.write(rec_date.isoformat(), ev)
                file_matched += 1
        except Exception:
            logger.exception("Error processing %s", key)
            continue
        total_records += file_records
        total_matched += file_matched
        if idx % progress_every == 0 or idx == len(keys):
            elapsed = time.monotonic() - t0
            rate = total_records / max(elapsed, 1e-6)
            logger.info(
                "[phase1 %d/%d] records=%s matched=%s days=%d rate=%.0f rec/s elapsed=%.1fs",
                idx, len(keys), f"{total_records:,}", f"{total_matched:,}",
                len(pool.date_files()), rate, elapsed,
            )

    pool.close_all()
    logger.info("Phase 1 complete. Total records=%s matched=%s", f"{total_records:,}", f"{total_matched:,}")
    return total_records, total_matched


# ---------------------------------------------------------------------------
# Phase 2: per-day derivation + DB write
# ---------------------------------------------------------------------------

def _hash_session_id(device_id: str, start_ts: datetime) -> str:
    """Stable synthetic source_event_id so re-runs are idempotent."""
    h = hashlib.sha256(f"{device_id}|{start_ts.isoformat()}".encode("utf-8")).hexdigest()
    return f"s3:{h[:32]}"


@dataclass
class DayAgg:
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


def read_day_events(path: Path) -> tuple[DayAgg, list[EventRow], dict[str, list[tuple[datetime, Optional[float], Optional[float]]]]]:
    """Read a per-day JSONL.gz file. Return aggregates + EventRows + per-device curves (for session time series)."""
    agg = DayAgg()
    rows: list[EventRow] = []
    curves: dict[str, list[tuple[datetime, Optional[float], Optional[float]]]] = defaultdict(list)
    with gzip.open(path, mode="rt", encoding="utf-8") as gz:
        for line in gz:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            did = e["d"]
            ts = datetime.fromtimestamp(e["t"], tz=timezone.utc)
            agg.active_device_ids.add(did)
            agg.total_events += 1
            agg.hour_counts[ts.hour] += 1
            if e.get("e"): agg.engaged_device_ids.add(did)
            if e.get("err"): agg.error_events += 1
            if (r := e.get("r")) is not None:
                agg.rssi_sum += r; agg.rssi_count += 1
            if (f := e.get("f")): agg.firmware_counts[f] += 1
            if (g := e.get("g")): agg.model_counts[g] += 1
            if (tt := e.get("tt")) is not None and tt > 0:
                agg.cook_temp_sum += tt; agg.cook_temp_count += 1

            rows.append(EventRow(
                device_id=did,
                sample_timestamp=ts,
                created_at=ts,
                current_temp=e.get("ct"),
                target_temp=e.get("tt"),
                rssi=e.get("r"),
                firmware_version=e.get("f"),
                grill_type=e.get("g"),
                engaged=bool(e.get("e")),
                error_codes_json=e.get("err") or [],
            ))
            curves[did].append((ts, e.get("ct"), e.get("fan")))
    return agg, rows, curves


def build_full_sessions(
    rows: list[EventRow],
    curves: dict[str, list[tuple[datetime, Optional[float], Optional[float]]]],
) -> list[dict[str, Any]]:
    """Derive sessions (via the shared LiteDerivedSession pipeline) and
    attach richer fields (temp curve, fan curve, manual_override_rate)
    needed for the telemetry_sessions row."""
    by_device: dict[str, list[EventRow]] = defaultdict(list)
    for r in rows:
        by_device[r.device_id].append(r)

    out: list[dict[str, Any]] = []
    for did, evs in by_device.items():
        sessions: list[LiteDerivedSession] = derive_sessions_from_rows(did, evs)
        dev_curve = sorted(curves.get(did, []), key=lambda x: x[0])
        for s in sessions:
            dur = int((s.end_ts - s.start_ts).total_seconds()) if s.start_ts and s.end_ts else 0
            in_window = [(t, ct, fan) for (t, ct, fan) in dev_curve if s.start_ts <= t <= s.end_ts]
            temp_series = [{"t": t.isoformat(), "c": ct} for (t, ct, _) in in_window if ct is not None]
            fan_series = [{"t": t.isoformat(), "f": fan} for (t, _, fan) in in_window if fan is not None]
            error_codes = sorted({int(ec) for ev in evs for ec in (ev.error_codes_json or []) if s.start_ts <= (ev.sample_timestamp or ev.created_at) <= s.end_ts}) if s.error_count else []
            src_id = _hash_session_id(did, s.start_ts)
            # time to stabilization not exposed on LiteDerivedSession — derive from temp_series
            tts_seconds = None
            if s.stabilized and s.target_temp is not None and temp_series:
                stable_hits = 0
                for pt in temp_series:
                    c = pt["c"]
                    if c is None: continue
                    if abs(c - s.target_temp) <= 15:
                        stable_hits += 1
                        if stable_hits >= 3:
                            tts_seconds = int((datetime.fromisoformat(pt["t"]) - s.start_ts).total_seconds())
                            break
                    else:
                        stable_hits = 0
            out.append({
                "source_event_id": src_id,
                "device_id": did,
                "user_id": None,
                "session_id": None,
                "grill_type": s.grill_type,
                "firmware_version": s.firmware_version,
                "target_temp": s.target_temp,
                "session_start": s.start_ts,
                "session_end": s.end_ts,
                "session_duration_seconds": dur,
                "disconnect_events": 1 if s.disconnect_proxy else 0,
                "manual_overrides": 0,
                "error_count": s.error_count,
                "error_codes_json": json.dumps(error_codes),
                "actual_temp_time_series": json.dumps(temp_series[:600]),  # cap at 600 points (~5h at 30s cadence)
                "fan_output_time_series": json.dumps(fan_series[:600]),
                "temp_stability_score": float(s.stability_score or 0.0),
                "time_to_stabilization_seconds": tts_seconds,
                "firmware_health_score": 1.0 if s.error_count == 0 else max(0.0, 1.0 - s.error_count / 10.0),
                "session_reliability_score": float(s.stability_score or 0.0) if s.session_success else 0.0,
                "manual_override_rate": 0.0,
                "cook_success": bool(s.session_success),
                "raw_payload": json.dumps({"archetype": s.archetype, "completed": s.completed, "overshoot": s.overshoot}),
            })
    return out


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_db_dsn() -> str:
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        raise RuntimeError("DATABASE_URL not set")
    for pfx in ("postgresql+psycopg://", "postgresql+psycopg2://", "postgresql+asyncpg://"):
        if raw.startswith(pfx):
            return "postgresql://" + raw[len(pfx):]
    return raw


UPSERT_DAILY_SQL = """
INSERT INTO telemetry_history_daily (
    business_date, active_devices, engaged_devices, total_events,
    avg_rssi, error_events, firmware_distribution, model_distribution,
    avg_cook_temp, peak_hour_distribution, session_count, successful_sessions,
    cook_styles_json, cook_style_details_json, temp_range_json, duration_range_json,
    unique_devices_seen, source, updated_at
) VALUES (
    %(business_date)s, %(active_devices)s, %(engaged_devices)s, %(total_events)s,
    %(avg_rssi)s, %(error_events)s, %(firmware_distribution)s, %(model_distribution)s,
    %(avg_cook_temp)s, %(peak_hour_distribution)s, %(session_count)s, %(successful_sessions)s,
    %(cook_styles_json)s, %(cook_style_details_json)s, %(temp_range_json)s, %(duration_range_json)s,
    %(unique_devices_seen)s, %(source)s, NOW()
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

INSERT_SESSION_SQL = """
INSERT INTO telemetry_sessions (
    source_event_id, device_id, user_id, session_id, grill_type, firmware_version,
    target_temp, session_start, session_end, session_duration_seconds,
    disconnect_events, manual_overrides, error_count, error_codes_json,
    actual_temp_time_series, fan_output_time_series, temp_stability_score,
    time_to_stabilization_seconds, firmware_health_score, session_reliability_score,
    manual_override_rate, cook_success, raw_payload, created_at, updated_at
) VALUES (
    %(source_event_id)s, %(device_id)s, %(user_id)s, %(session_id)s, %(grill_type)s, %(firmware_version)s,
    %(target_temp)s, %(session_start)s, %(session_end)s, %(session_duration_seconds)s,
    %(disconnect_events)s, %(manual_overrides)s, %(error_count)s, %(error_codes_json)s::jsonb,
    %(actual_temp_time_series)s::jsonb, %(fan_output_time_series)s::jsonb, %(temp_stability_score)s,
    %(time_to_stabilization_seconds)s, %(firmware_health_score)s, %(session_reliability_score)s,
    %(manual_override_rate)s, %(cook_success)s, %(raw_payload)s::jsonb, NOW(), NOW()
)
ON CONFLICT (source_event_id) DO NOTHING
"""


def days_with_sessions(conn) -> set[str]:
    """Returns set of YYYY-MM-DD where session_count > 0 already."""
    with conn.cursor() as cur:
        cur.execute("SELECT business_date FROM telemetry_history_daily WHERE session_count IS NOT NULL AND session_count > 0")
        return {str(r[0]) for r in cur.fetchall()}


def phase2_derive_and_write(
    temp_dir: Path,
    skip_existing: bool = True,
    delete_processed: bool = True,
) -> None:
    import psycopg
    day_files = sorted(temp_dir.glob("*.jsonl.gz"))
    logger.info("Phase 2: %d day files to process", len(day_files))
    dsn = get_db_dsn()
    with psycopg.connect(dsn) as conn:
        already = days_with_sessions(conn) if skip_existing else set()
        if already:
            logger.info("Phase 2: %d days already have sessions; will skip", len(already))

        for idx, path in enumerate(day_files, 1):
            date_key = path.stem.split(".")[0]  # YYYY-MM-DD
            if skip_existing and date_key in already:
                if delete_processed:
                    path.unlink(missing_ok=True)
                continue
            t0 = time.monotonic()
            try:
                agg, rows, curves = read_day_events(path)
                if not rows:
                    continue
                full_sessions = build_full_sessions(rows, curves)
                # Build lite sessions for cook-column aggregates
                by_device: dict[str, list[EventRow]] = defaultdict(list)
                for r in rows:
                    by_device[r.device_id].append(r)
                lite_all: list[LiteDerivedSession] = []
                for did, evs in by_device.items():
                    lite_all.extend(derive_sessions_from_rows(did, evs))
                cook_cols = build_daily_cook_columns(lite_all, agg.active_device_ids)

                daily_row = {
                    "business_date": date_key,
                    "active_devices": len(agg.active_device_ids),
                    "engaged_devices": len(agg.engaged_device_ids),
                    "total_events": agg.total_events,
                    "avg_rssi": round(agg.rssi_sum / agg.rssi_count, 2) if agg.rssi_count > 0 else None,
                    "error_events": agg.error_events,
                    "firmware_distribution": json.dumps(dict(agg.firmware_counts), sort_keys=True),
                    "model_distribution": json.dumps(dict(agg.model_counts), sort_keys=True),
                    "avg_cook_temp": round(agg.cook_temp_sum / agg.cook_temp_count, 2) if agg.cook_temp_count > 0 else None,
                    "peak_hour_distribution": json.dumps({str(h): c for h, c in sorted(agg.hour_counts.items())}),
                    "session_count": cook_cols.get("session_count", 0),
                    "successful_sessions": cook_cols.get("successful_sessions", 0),
                    "cook_styles_json": json.dumps(cook_cols.get("cook_styles_json", {})),
                    "cook_style_details_json": json.dumps(cook_cols.get("cook_style_details_json", {})),
                    "temp_range_json": json.dumps(cook_cols.get("temp_range_json", {})),
                    "duration_range_json": json.dumps(cook_cols.get("duration_range_json", {})),
                    "unique_devices_seen": cook_cols.get("unique_devices_seen") or len(agg.active_device_ids),
                    "source": "ddb_export_backfill_v2",
                }
                with conn.cursor() as cur:
                    cur.execute(UPSERT_DAILY_SQL, daily_row)
                    if full_sessions:
                        cur.executemany(INSERT_SESSION_SQL, full_sessions)
                conn.commit()
                dt = time.monotonic() - t0
                logger.info(
                    "[phase2 %d/%d] %s: events=%s sessions=%d (success=%d) active=%d engaged=%d elapsed=%.1fs",
                    idx, len(day_files), date_key,
                    f"{agg.total_events:,}", daily_row["session_count"], daily_row["successful_sessions"],
                    daily_row["active_devices"], daily_row["engaged_devices"], dt,
                )
                if delete_processed:
                    path.unlink(missing_ok=True)
            except Exception:
                logger.exception("Phase 2 failed for %s", date_key)
                conn.rollback()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _parse_date(s: str) -> date:
    try: return date.fromisoformat(s)
    except ValueError: raise argparse.ArgumentTypeError(f"bad date {s}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start-date", type=_parse_date, default=DEFAULT_START_DATE)
    p.add_argument("--end-date", type=_parse_date, default=None)
    p.add_argument("--bucket", default=S3_BUCKET)
    p.add_argument("--prefix", default=S3_PREFIX)
    p.add_argument("--temp-dir", type=Path, default=DEFAULT_TEMP_DIR)
    p.add_argument("--env-file", type=Path, default=ENV_FILE)
    p.add_argument("--skip-phase1", action="store_true", help="Skip S3 extraction; reuse temp_dir contents.")
    p.add_argument("--skip-phase2", action="store_true", help="Extract only; do not derive/write.")
    p.add_argument("--skip-existing-sessions", action="store_true", default=True)
    p.add_argument("--no-skip-existing-sessions", dest="skip_existing_sessions", action="store_false")
    p.add_argument("--keep-temp", action="store_true", help="Do not delete day files after processing.")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    load_env(args.env_file)

    logger.info("v2 backfill starting.  start=%s end=%s temp_dir=%s",
                args.start_date, args.end_date or "(none)", args.temp_dir)

    if not args.skip_phase1:
        s3 = get_s3_client()
        phase1_extract_events(s3, args.bucket, args.prefix, args.start_date, args.end_date, args.temp_dir)

    if args.skip_phase2:
        logger.info("Phase 2 skipped by flag.")
        return 0

    phase2_derive_and_write(args.temp_dir, skip_existing=args.skip_existing_sessions, delete_processed=not args.keep_temp)

    # Clean up temp dir if empty
    try:
        if not any(args.temp_dir.iterdir()):
            shutil.rmtree(args.temp_dir, ignore_errors=True)
    except Exception:
        pass

    logger.info("v2 backfill complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
