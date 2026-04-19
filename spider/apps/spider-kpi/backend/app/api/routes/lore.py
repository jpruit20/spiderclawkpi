"""Company-lore API surface — seasonality, event timeline, lore ledger.

Phase 1 (2026-04-19) ships the seasonality engine. Event Timeline +
Lore Ledger endpoints land here in subsequent phases. Single prefix
``/api/lore`` so the frontend has a consistent namespace as the surface
grows.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_dashboard_session
from app.services.seasonality import (
    METRICS,
    baselines_for_range,
    metric_context,
)


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/lore",
    tags=["lore"],
    dependencies=[Depends(require_dashboard_session)],
)


def _parse_iso_date(s: str, field: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid {field}: expected YYYY-MM-DD")


@router.get("/metrics")
def list_metrics() -> dict[str, Any]:
    """Return the metrics the seasonality engine has baselines for.
    Frontend calls this to know what's available for hot/cold badges."""
    return {
        "metrics": [
            {"name": m.name, "source": f"{m.source_table}.{m.source_column}"}
            for m in METRICS
        ],
    }


@router.get("/seasonal-baseline")
def seasonal_baseline(
    metric: str = Query(..., description="metric name (see /api/lore/metrics)"),
    start: str = Query(..., description="YYYY-MM-DD start date (inclusive)"),
    end: str = Query(..., description="YYYY-MM-DD end date (inclusive)"),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Return p10/p25/p50/p75/p90 baseline per date in [start, end].

    Suitable for rendering a shaded baseline-band overlay on any
    time-series chart. Each day in the range has the seasonal
    distribution for that day-of-year (aggregated across prior years).
    """
    start_d = _parse_iso_date(start, "start")
    end_d = _parse_iso_date(end, "end")
    if end_d < start_d:
        raise HTTPException(status_code=400, detail="end must be >= start")
    if (end_d - start_d).days > 730:
        raise HTTPException(status_code=400, detail="range cannot exceed 730 days")

    rows = baselines_for_range(db, metric, start_d, end_d)
    years_covered = sorted({int(y) for r in rows for y in _row_years(r)})
    return {
        "metric": metric,
        "window": {"start": start, "end": end, "days": (end_d - start_d).days + 1},
        "years_in_baseline": years_covered,
        "baseline": rows,
    }


def _row_years(row: dict[str, Any]) -> list[str]:
    # Baseline row doesn't currently expose per-sample years in this view;
    # future-proof the shape. For now return empty.
    return []


@router.get("/metric-context")
def get_metric_context(
    metric: str = Query(..., description="metric name"),
    on_date: str = Query(..., description="YYYY-MM-DD date to interpret"),
    value: Optional[float] = Query(None, description="override current value (default: fetch from source)"),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Return seasonal interpretation for one metric on one date:
    current value, baseline distribution for that day-of-year, verdict
    (running_hot / normal / running_cold / etc.), percentile rank, and
    delta vs historical median. Used for "running hot" badges on KPI
    tiles.
    """
    d = _parse_iso_date(on_date, "on_date")
    ctx = metric_context(db, metric, d, current_value=value)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"unknown metric: {metric}")
    return {
        "metric": ctx.metric_name,
        "on_date": ctx.on_date.isoformat(),
        "day_of_year": ctx.day_of_year,
        "current_value": ctx.current_value,
        "baseline": ctx.baseline,
        "year_count": ctx.year_count,
        "verdict": ctx.verdict,
        "percentile_rank": ctx.percentile_rank,
        "delta_vs_median_pct": ctx.delta_vs_median_pct,
    }
