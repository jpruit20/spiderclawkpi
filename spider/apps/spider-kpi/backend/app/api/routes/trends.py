"""Trend deltas + anomaly endpoint.

Powers the cross-page KPI tile trend chips (7d/28d arrows + % change)
and the anomaly badges. One endpoint, multi-metric, so the frontend
can request all the trends a card needs in a single round-trip.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.services.trend_analysis import (
    cook_success_rate_series,
    detect_anomaly,
    kpi_daily_series,
    telemetry_history_daily_series,
    trend_delta,
    two_window_split,
)


router = APIRouter(prefix="/api/trends", tags=["trends"])


# Map of "metric key" → (table, column, label, direction-where-up-is-good)
# direction-where-up-is-good controls whether an upward trend renders
# green or red. Revenue up = good (green); ticket count up = bad (red).
METRICS: dict[str, dict[str, Any]] = {
    "revenue":             {"table": "kpi", "col": "revenue",             "label": "Revenue",              "up_is_good": True},
    "orders":              {"table": "kpi", "col": "orders",              "label": "Orders",               "up_is_good": True},
    "tickets_created":     {"table": "kpi", "col": "tickets_created",     "label": "Tickets created",      "up_is_good": False},
    "csat":                {"table": "kpi", "col": "csat",                "label": "CSAT",                 "up_is_good": True},
    "first_response_time": {"table": "kpi", "col": "first_response_time", "label": "First-response time",  "up_is_good": False},
    "active_devices":      {"table": "tel", "col": "active_devices",      "label": "Active devices",       "up_is_good": True},
    "telemetry_sessions":  {"table": "tel", "col": "session_count",       "label": "Cook sessions",        "up_is_good": True},
    "telemetry_errors":    {"table": "tel", "col": "error_events",        "label": "Telemetry errors",     "up_is_good": False},
    # Cook success rate is derived (successful_sessions / session_count),
    # so it doesn't map to a single column — special-cased in _series.
    "cook_success_rate":   {"table": "derived", "col": "cook_success_rate", "label": "Cook success rate",  "up_is_good": True},
}


def _series(db: Session, metric_key: str, days: int = 35) -> list[float]:
    spec = METRICS[metric_key]
    if spec["table"] == "kpi":
        return kpi_daily_series(db, spec["col"], days=days)
    if spec["table"] == "tel":
        return telemetry_history_daily_series(db, spec["col"], days=days)
    if spec["table"] == "derived" and spec["col"] == "cook_success_rate":
        return cook_success_rate_series(db, days=days)
    raise ValueError(f"unknown metric source for {metric_key!r}")


@router.get("/all")
def all_trends(
    days_baseline: int = 35,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Compute 7d-vs-prior-7d trend + 28d rolling-baseline anomaly for
    every registered metric. One round-trip; the frontend picks which
    to render where.

    The "current" value is the **mean of the trailing 7 daily values**;
    "prior" is the mean of the 7 daily values before that. The arrow +
    delta_pct is the change between those two daily-average means. The
    "anomaly" compares current to the prior 28-day daily-mean baseline.

    Active operator-set targets are embedded per metric (read from
    ``kpi_targets`` with seasonal-window resolution). The frontend
    uses these to color tiles green/red and show "% of target."
    """
    from app.services.kpi_targets import get_active_targets
    active_targets = get_active_targets(db)

    out: dict[str, Any] = {}
    for key, spec in METRICS.items():
        try:
            series = _series(db, key, days=days_baseline)
        except Exception as exc:
            out[key] = {"error": str(exc)[:200]}
            continue
        target = active_targets.get(key)
        if not series:
            out[key] = {"label": spec["label"], "available": False, "target": target}
            continue
        cur_7d, prior_7d = two_window_split(series, current_window_days=7)
        delta = trend_delta(cur_7d, prior_7d)
        baseline_history = series[:-7] if len(series) > 7 else series
        anomaly = detect_anomaly(cur_7d, baseline_history)

        # Compute "% of target" if a target exists. For min-direction
        # (e.g. revenue), 100% means we're at target; >100% beat. For
        # max-direction (e.g. tickets_created), 100% means we're at
        # target; >100% over the cap (bad).
        target_progress_pct: Optional[float] = None
        target_hit: Optional[bool] = None
        if target and target.get("target_value"):
            tv = float(target["target_value"])
            if tv > 0:
                target_progress_pct = round((cur_7d / tv) * 100, 1)
                if target.get("direction") == "max":
                    target_hit = cur_7d <= tv
                else:
                    target_hit = cur_7d >= tv

        out[key] = {
            "label": spec["label"],
            "available": True,
            "up_is_good": spec["up_is_good"],
            "trend_7d": delta.to_dict(),
            "anomaly": anomaly.to_dict(),
            "target": target,
            "target_progress_pct": target_progress_pct,
            "target_hit": target_hit,
        }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "methodology": {
            "current": "mean of the 7 most-recent daily values",
            "prior": "mean of the 7 daily values immediately before the current window",
            "delta_pct": "(current - prior) / abs(prior) × 100",
            "anomaly": "z-score of current vs the prior 28-day daily-mean baseline",
            "target_progress_pct": "(current / target_value) × 100 — 100 means at target",
        },
        "metrics": out,
    }


@router.get("/{metric_key}")
def single_trend(metric_key: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    if metric_key not in METRICS:
        return {"error": f"unknown metric. Valid: {sorted(METRICS)}"}
    spec = METRICS[metric_key]
    series = _series(db, metric_key, days=35)
    if not series:
        return {"label": spec["label"], "available": False}
    cur_7d, prior_7d = two_window_split(series, current_window_days=7)
    delta = trend_delta(cur_7d, prior_7d)
    baseline_history = series[:-7] if len(series) > 7 else series
    anomaly = detect_anomaly(cur_7d, baseline_history)
    return {
        "label": spec["label"],
        "available": True,
        "up_is_good": spec["up_is_good"],
        "trend_7d": delta.to_dict(),
        "anomaly": anomaly.to_dict(),
        "series_tail": series[-14:],
    }
