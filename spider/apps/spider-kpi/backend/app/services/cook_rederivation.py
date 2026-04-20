"""Re-derive PID-quality / intent / outcome columns on telemetry_sessions.

The 2026-04-18 migration added the intent+outcome+PID-quality model to
``telemetry_sessions`` (cook_intent, cook_outcome, held_target,
in_control_pct, disturbance_count, total_disturbance_seconds,
avg_recovery_seconds, max_overshoot_f, max_undershoot_f, post_reach_samples),
but existing S3-backfilled rows were left NULL — the ingestion paths
don't score on write. This service walks those rows, calls
``score_session_from_temp_series`` on each, and writes the new columns
back. Runs incrementally: only touches rows where ``cook_intent IS NULL``.

It also rebuilds the matching daily aggregates on
``telemetry_history_daily`` so the dashboard's Temperature Quality
Control panel and Firmware Impact Timeline light up.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import TelemetryHistoryDaily, TelemetrySession
from app.services.cook_classification import (
    build_daily_quality_columns,
    score_session_from_temp_series,
)

logger = logging.getLogger(__name__)

REACHED_TOLERANCE_F = 10.0
DISCONNECT_GAP_SECONDS = 600  # 10 min — same as legacy proxy logic


def _infer_reached_target(
    temp_series: list[dict],
    target_temp: float | None,
) -> bool:
    if target_temp is None or target_temp <= 0 or not temp_series:
        return False
    threshold = float(target_temp) - REACHED_TOLERANCE_F
    for p in temp_series:
        if not isinstance(p, dict):
            continue
        try:
            if float(p.get("c")) >= threshold:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _infer_disconnect_proxy(temp_series: list[dict], stored_disconnect_events: int) -> bool:
    if stored_disconnect_events and stored_disconnect_events > 0:
        return True
    if not temp_series or len(temp_series) < 2:
        return False
    prev: datetime | None = None
    max_gap = 0
    for p in temp_series:
        if not isinstance(p, dict):
            continue
        raw = p.get("t")
        if not raw:
            continue
        try:
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if prev is not None:
            gap = int((ts - prev).total_seconds())
            if gap > max_gap:
                max_gap = gap
        prev = ts
    return max_gap > DISCONNECT_GAP_SECONDS


def rederive_session_quality(
    db: Session,
    *,
    batch_size: int = 2000,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """Backfill new-model columns on every ``telemetry_sessions`` row that's
    still NULL. Safe to run repeatedly — idempotent and incremental.

    Returns stats dict.
    """
    started = time.monotonic()
    stats: dict[str, Any] = {
        "scanned": 0,
        "scored": 0,
        "skipped_no_curve": 0,
        "batches": 0,
    }

    while True:
        rows = db.execute(
            select(TelemetrySession)
            .where(TelemetrySession.cook_intent.is_(None))
            .order_by(TelemetrySession.id)
            .limit(batch_size)
        ).scalars().all()
        if not rows:
            break

        stats["batches"] += 1
        for s in rows:
            stats["scanned"] += 1
            series = s.actual_temp_time_series or []
            duration = int(s.session_duration_seconds or 0)
            target = float(s.target_temp) if s.target_temp is not None else None
            reached = _infer_reached_target(series, target)
            disconnect = _infer_disconnect_proxy(series, s.disconnect_events or 0)
            scored = score_session_from_temp_series(
                temp_series_json=series,
                target_temp=target,
                duration_seconds=duration,
                disconnect_proxy=disconnect,
                error_count=int(s.error_count or 0),
                reached_target=reached,
            )
            s.cook_intent = scored["cook_intent"]
            s.cook_outcome = scored["cook_outcome"]
            s.held_target = bool(scored["held_target"])
            s.disturbance_count = int(scored.get("disturbance_count") or 0)
            s.total_disturbance_seconds = int(scored.get("total_disturbance_seconds") or 0)
            s.avg_recovery_seconds = (
                int(scored["avg_recovery_seconds"]) if scored.get("avg_recovery_seconds") is not None else None
            )
            s.in_control_pct = (
                float(scored["in_control_pct"]) if scored.get("in_control_pct") is not None else None
            )
            s.max_overshoot_f = (
                float(scored["max_overshoot_f"]) if scored.get("max_overshoot_f") is not None else None
            )
            s.max_undershoot_f = (
                float(scored["max_undershoot_f"]) if scored.get("max_undershoot_f") is not None else None
            )
            s.post_reach_samples = int(scored.get("post_reach_samples") or 0)
            if not series:
                stats["skipped_no_curve"] += 1
            else:
                stats["scored"] += 1
        db.commit()
        logger.info(
            "cook_rederivation batch %d: scanned=%d scored=%d",
            stats["batches"], stats["scanned"], stats["scored"],
        )
        if max_rows is not None and stats["scanned"] >= max_rows:
            break

    stats["duration_ms"] = int((time.monotonic() - started) * 1000)
    return stats


def rebuild_daily_quality_aggregates(
    db: Session,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    """Roll session-level cook_intent/outcome/PID metrics into
    ``telemetry_history_daily``. Rebuilds unconditionally — the aggregate
    columns are cheap to recompute and this keeps them consistent as the
    rederivation or new S3 batches add more rows.
    """
    started = time.monotonic()
    where_clauses = ["cook_intent IS NOT NULL", "session_start IS NOT NULL"]
    params: dict[str, Any] = {}
    if start_date is not None:
        where_clauses.append("session_start >= :start_ts")
        params["start_ts"] = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    if end_date is not None:
        where_clauses.append("session_start < :end_ts")
        params["end_ts"] = datetime.combine(end_date, datetime.min.time(), tzinfo=timezone.utc)

    sql = text(f"""
        SELECT DATE(session_start AT TIME ZONE 'UTC') AS d,
               cook_intent, cook_outcome, held_target,
               in_control_pct, disturbance_count,
               avg_recovery_seconds, max_overshoot_f
          FROM telemetry_sessions
         WHERE {" AND ".join(where_clauses)}
         ORDER BY d
    """)
    per_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for row in db.execute(sql, params):
        per_day[row.d].append({
            "cook_intent": row.cook_intent,
            "cook_outcome": row.cook_outcome,
            "held_target": row.held_target,
            "in_control_pct": row.in_control_pct,
            "disturbance_count": row.disturbance_count,
            "avg_recovery_seconds": row.avg_recovery_seconds,
            "max_overshoot_f": row.max_overshoot_f,
        })

    updated = 0
    for biz_date, scores in per_day.items():
        agg = build_daily_quality_columns(scores)
        row = db.execute(
            select(TelemetryHistoryDaily).where(TelemetryHistoryDaily.business_date == biz_date)
        ).scalars().first()
        if row is None:
            # No base telemetry_history_daily row yet — skip rather than
            # create an orphan; the nightly materializer owns row creation.
            continue
        row.cook_intents_json = agg["cook_intents_json"]
        row.cook_outcomes_json = agg["cook_outcomes_json"]
        row.held_target_sessions = agg["held_target_sessions"]
        row.target_seeking_sessions = agg["target_seeking_sessions"]
        row.held_target_rate = agg["held_target_rate"]
        row.avg_in_control_pct = agg["avg_in_control_pct"]
        row.avg_disturbances_per_cook = agg["avg_disturbances_per_cook"]
        row.avg_recovery_seconds = agg["avg_recovery_seconds"]
        row.avg_overshoot_f = agg["avg_overshoot_f"]
        updated += 1
    db.commit()
    return {
        "days_aggregated": len(per_day),
        "days_written": updated,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


def run_cook_rederivation(db: Session, *, max_rows: int | None = None) -> dict[str, Any]:
    """End-to-end: score any unscored sessions, then refresh daily aggregates."""
    rederive_stats = rederive_session_quality(db, max_rows=max_rows)
    agg_stats = rebuild_daily_quality_aggregates(db)
    return {"ok": True, "rederive": rederive_stats, "aggregate": agg_stats}
