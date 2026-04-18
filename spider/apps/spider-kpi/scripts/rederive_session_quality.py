#!/usr/bin/env python3
"""Populate the 2026-04-18 intent/outcome/PID-quality columns on
telemetry_sessions from the already-stored actual_temp_time_series
JSON. Then roll the daily aggregates (held_target_rate,
avg_in_control_pct, etc.) into telemetry_history_daily.

Safe to re-run: writes are idempotent (row PK + date).

Usage:
    python scripts/rederive_session_quality.py                # all sessions
    python scripts/rederive_session_quality.py --limit 500    # sample run
    python scripts/rederive_session_quality.py --only-missing # skip already-scored
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path


ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def _load_env(p: Path) -> None:
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
            v = v[1:-1]
        os.environ.setdefault(k.strip(), v)


_load_env(ENV_PATH)

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import text  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.services.cook_classification import (  # noqa: E402
    build_daily_quality_columns,
    score_session_from_temp_series,
)


logger = logging.getLogger("rederive_quality")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)


UPDATE_SESSION_SQL = """
UPDATE telemetry_sessions SET
    cook_intent              = :cook_intent,
    cook_outcome             = :cook_outcome,
    held_target              = :held_target,
    disturbance_count        = :disturbance_count,
    total_disturbance_seconds = :total_disturbance_seconds,
    avg_recovery_seconds     = :avg_recovery_seconds,
    in_control_pct           = :in_control_pct,
    max_overshoot_f          = :max_overshoot_f,
    max_undershoot_f         = :max_undershoot_f,
    post_reach_samples       = :post_reach_samples,
    updated_at               = NOW()
 WHERE id = :id
"""


UPDATE_DAILY_SQL = """
UPDATE telemetry_history_daily SET
    cook_intents_json          = CAST(:cook_intents_json AS JSONB),
    cook_outcomes_json         = CAST(:cook_outcomes_json AS JSONB),
    held_target_sessions       = :held_target_sessions,
    target_seeking_sessions    = :target_seeking_sessions,
    held_target_rate           = :held_target_rate,
    avg_in_control_pct         = :avg_in_control_pct,
    avg_disturbances_per_cook  = :avg_disturbances_per_cook,
    avg_recovery_seconds       = :avg_recovery_seconds,
    avg_overshoot_f            = :avg_overshoot_f,
    updated_at                 = NOW()
 WHERE business_date = :business_date
"""


def parse_ts(raw) -> dict:
    """temp_series is stored as JSONB — psycopg returns it as already-parsed
    list of dicts. If somehow stored as text, json.loads. Accept both."""
    if raw is None:
        return []
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return []


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--limit", type=int, default=None, help="Max sessions to process.")
    p.add_argument("--only-missing", action="store_true", help="Skip sessions with cook_intent already set.")
    p.add_argument("--no-daily", action="store_true", help="Skip the daily-rollup phase.")
    p.add_argument("--batch-size", type=int, default=200)
    args = p.parse_args()

    db = SessionLocal()
    try:
        # ── Phase 1: per-session re-derivation ────────────────────────
        where_clause = ""
        if args.only_missing:
            where_clause = "WHERE cook_intent IS NULL"
        limit_clause = f" LIMIT {args.limit}" if args.limit else ""
        count_sql = f"SELECT COUNT(*) FROM telemetry_sessions {where_clause}"
        total = int(db.execute(text(count_sql)).scalar() or 0)
        if total == 0:
            logger.info("No sessions to score.")
            if not args.no_daily:
                _rollup_daily(db)
            return 0

        logger.info("Re-scoring %d sessions (only_missing=%s, limit=%s)", total, args.only_missing, args.limit)

        select_sql = f"""
            SELECT id, target_temp, session_duration_seconds, disconnect_events,
                   error_count, actual_temp_time_series,
                   session_start, session_end
              FROM telemetry_sessions
            {where_clause}
             ORDER BY id
            {limit_clause}
        """

        t0 = time.monotonic()
        processed = 0
        updates: list[dict] = []
        updated_dates: set = set()

        for row in db.execute(text(select_sql)).mappings():
            # Heuristic reached_target: we use the new score function's own
            # logic; but the scorer needs reached_target as an input. Compute
            # it from the series directly.
            ts_json = parse_ts(row["actual_temp_time_series"])
            target_temp = row["target_temp"]
            reached = False
            if target_temp and isinstance(ts_json, list):
                for pt in ts_json:
                    if isinstance(pt, dict):
                        c = pt.get("c")
                        try:
                            if c is not None and float(c) >= float(target_temp) - 10:
                                reached = True
                                break
                        except (TypeError, ValueError):
                            continue

            scored = score_session_from_temp_series(
                temp_series_json=ts_json if isinstance(ts_json, list) else [],
                target_temp=float(target_temp) if target_temp is not None else None,
                duration_seconds=int(row["session_duration_seconds"] or 0),
                disconnect_proxy=bool((row["disconnect_events"] or 0) > 0),
                error_count=int(row["error_count"] or 0),
                reached_target=reached,
            )
            updates.append({
                "id": row["id"],
                "cook_intent": scored["cook_intent"],
                "cook_outcome": scored["cook_outcome"],
                "held_target": scored["held_target"],
                "disturbance_count": scored["disturbance_count"],
                "total_disturbance_seconds": scored["total_disturbance_seconds"],
                "avg_recovery_seconds": scored["avg_recovery_seconds"],
                "in_control_pct": scored["in_control_pct"],
                "max_overshoot_f": scored["max_overshoot_f"],
                "max_undershoot_f": scored["max_undershoot_f"],
                "post_reach_samples": scored["post_reach_samples"],
            })
            if row["session_start"]:
                updated_dates.add(row["session_start"].date())

            if len(updates) >= args.batch_size:
                db.execute(text(UPDATE_SESSION_SQL), updates)
                db.commit()
                processed += len(updates)
                updates.clear()
                elapsed = time.monotonic() - t0
                rate = processed / max(elapsed, 1e-6)
                logger.info("[sessions] %d/%d  (%.0f/s)", processed, total, rate)

        if updates:
            db.execute(text(UPDATE_SESSION_SQL), updates)
            db.commit()
            processed += len(updates)

        elapsed = time.monotonic() - t0
        logger.info("Session phase complete: %d scored in %.1fs", processed, elapsed)

        # ── Phase 2: roll into telemetry_history_daily ────────────────
        if not args.no_daily:
            _rollup_daily(db, target_dates=updated_dates)

        return 0
    finally:
        db.close()


def _rollup_daily(db, target_dates: set | None = None) -> None:
    """Compute per-day aggregates over the newly-scored sessions and
    upsert into telemetry_history_daily."""
    logger.info("Rolling up daily quality aggregates…")
    # Group scored sessions by business_date (UTC date of session_start).
    if target_dates:
        placeholders = ",".join(f":d{i}" for i in range(len(target_dates)))
        params = {f"d{i}": d for i, d in enumerate(sorted(target_dates))}
        sql = f"""
            SELECT DATE(session_start) AS d,
                   cook_intent, cook_outcome, held_target,
                   disturbance_count, avg_recovery_seconds,
                   in_control_pct, max_overshoot_f
              FROM telemetry_sessions
             WHERE cook_intent IS NOT NULL
               AND DATE(session_start) IN ({placeholders})
             ORDER BY d
        """
        rows = db.execute(text(sql), params).mappings().all()
    else:
        sql = """
            SELECT DATE(session_start) AS d,
                   cook_intent, cook_outcome, held_target,
                   disturbance_count, avg_recovery_seconds,
                   in_control_pct, max_overshoot_f
              FROM telemetry_sessions
             WHERE cook_intent IS NOT NULL
             ORDER BY d
        """
        rows = db.execute(text(sql)).mappings().all()

    by_date: dict = defaultdict(list)
    for r in rows:
        d = r["d"]
        if d is None:
            continue
        by_date[d].append({
            "cook_intent": r["cook_intent"],
            "cook_outcome": r["cook_outcome"],
            "held_target": r["held_target"],
            "disturbance_count": r["disturbance_count"],
            "avg_recovery_seconds": r["avg_recovery_seconds"],
            "in_control_pct": r["in_control_pct"],
            "max_overshoot_f": r["max_overshoot_f"],
        })

    logger.info("Daily rollup target: %d dates", len(by_date))
    for d, scores in by_date.items():
        agg = build_daily_quality_columns(scores)
        db.execute(
            text(UPDATE_DAILY_SQL),
            {
                "business_date": d,
                "cook_intents_json": json.dumps(agg["cook_intents_json"]),
                "cook_outcomes_json": json.dumps(agg["cook_outcomes_json"]),
                "held_target_sessions": agg["held_target_sessions"],
                "target_seeking_sessions": agg["target_seeking_sessions"],
                "held_target_rate": agg["held_target_rate"],
                "avg_in_control_pct": agg["avg_in_control_pct"],
                "avg_disturbances_per_cook": agg["avg_disturbances_per_cook"],
                "avg_recovery_seconds": agg["avg_recovery_seconds"],
                "avg_overshoot_f": agg["avg_overshoot_f"],
            },
        )
    db.commit()
    logger.info("Daily rollup complete.")


if __name__ == "__main__":
    raise SystemExit(main())
