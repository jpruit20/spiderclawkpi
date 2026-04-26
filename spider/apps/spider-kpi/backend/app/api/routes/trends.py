"""Trend deltas + anomaly endpoint.

Powers the cross-page KPI tile trend chips (7d/28d arrows + % change)
and the anomaly badges. One endpoint, multi-metric, so the frontend
can request all the trends a card needs in a single round-trip.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.services.trend_analysis import (
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
    "revenue":             {"table": "kpi", "col": "revenue",            "label": "Revenue",              "up_is_good": True},
    "orders":              {"table": "kpi", "col": "orders",             "label": "Orders",               "up_is_good": True},
    "cook_success_rate":   {"table": "kpi", "col": "cook_success_rate",  "label": "Cook success rate",    "up_is_good": True},
    "active_devices":      {"table": "kpi", "col": "active_devices",     "label": "Active devices",       "up_is_good": True},
    "tickets_created":     {"table": "kpi", "col": "tickets_created",    "label": "Tickets created",      "up_is_good": False},
    "csat":                {"table": "kpi", "col": "csat",               "label": "CSAT",                 "up_is_good": True},
    "first_response_hours":{"table": "kpi", "col": "first_response_hours","label": "First-response hrs",  "up_is_good": False},
    "telemetry_active":    {"table": "tel", "col": "active_devices",     "label": "Telemetry active",     "up_is_good": True},
    "telemetry_sessions":  {"table": "tel", "col": "session_count",      "label": "Cook sessions",        "up_is_good": True},
    "telemetry_errors":    {"table": "tel", "col": "error_events",       "label": "Telemetry errors",     "up_is_good": False},
}


def _series(db: Session, metric_key: str, days: int = 35) -> list[float]:
    spec = METRICS[metric_key]
    if spec["table"] == "kpi":
        return kpi_daily_series(db, spec["col"], days=days)
    return telemetry_history_daily_series(db, spec["col"], days=days)


@router.get("/all")
def all_trends(
    days_baseline: int = 35,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Compute 7d-vs-prior-7d trend + 28d rolling-baseline anomaly for
    every registered metric. One round-trip; the frontend picks which
    to render where."""
    out: dict[str, Any] = {}
    for key, spec in METRICS.items():
        try:
            series = _series(db, key, days=days_baseline)
        except Exception as exc:
            out[key] = {"error": str(exc)[:200]}
            continue
        if not series:
            out[key] = {"label": spec["label"], "available": False}
            continue
        cur_7d, prior_7d = two_window_split(series, current_window_days=7)
        delta = trend_delta(cur_7d, prior_7d)
        # Anomaly: how does the 7d-current value compare to the prior
        # 28-day baseline (everything except the last 7d)?
        baseline_history = series[:-7] if len(series) > 7 else series
        anomaly = detect_anomaly(cur_7d, baseline_history)
        out[key] = {
            "label": spec["label"],
            "available": True,
            "up_is_good": spec["up_is_good"],
            "trend_7d": delta.to_dict(),
            "anomaly": anomaly.to_dict(),
        }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
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
