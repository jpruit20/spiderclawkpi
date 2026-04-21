"""Command Center endpoints — weekly Opus-curated priority gauges."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_dashboard_session
from app.api.routes.auth import get_user_from_request
from app.models import WeeklyGaugeSelection
from app.services.weekly_gauges_catalog import CATALOG, resolve_metric
from app.services.weekly_gauges_selector import ANCHOR_KEYS
from app.services.weekly_gauges_selector import (
    _iso_week_start,
    run_weekly_gauge_selection,
)


router = APIRouter(
    prefix="/api/command-center",
    tags=["command-center"],
    dependencies=[Depends(require_dashboard_session)],
)


def _serialize_gauge(db: Session, row: WeeklyGaugeSelection) -> dict[str, Any]:
    meta = CATALOG.get(row.metric_key)
    live = resolve_metric(db, row.metric_key) or {
        "value": 0.0, "display_value": "—", "sparkline": [],
        "prior_week": None, "change_pct": None,
    }
    return {
        "rank": row.rank,
        "metric_key": row.metric_key,
        "label": meta.label if meta else row.metric_key,
        "unit": meta.unit if meta else "",
        "category": meta.category if meta else "unknown",
        "direction": meta.direction if meta else "higher_better",
        "description": meta.description if meta else "",
        "drill_href": meta.drill_href if meta else None,
        "gauge_style": row.gauge_style,
        "rationale": row.rationale,
        "target_value": row.target_value if row.target_value is not None else (meta.default_target if meta else None),
        "healthy_band_low": row.healthy_band_low,
        "healthy_band_high": row.healthy_band_high,
        "pinned": row.pinned,
        "selected_by": row.selected_by,
        "selected_at": row.selected_at.isoformat() if row.selected_at else None,
        "value": live.get("value"),
        "display_value": live.get("display_value"),
        "sparkline": live.get("sparkline", []),
        "prior_week": live.get("prior_week"),
        "change_pct": live.get("change_pct"),
    }


@router.get("/weekly-gauges")
def get_weekly_gauges(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Return the current week's 8 gauges with live values + sparklines."""
    today = date.today()
    week_start = _iso_week_start(today)
    rows = db.execute(
        select(WeeklyGaugeSelection)
        .where(WeeklyGaugeSelection.iso_week_start == week_start)
        .order_by(WeeklyGaugeSelection.rank)
    ).scalars().all()

    # If we have no selection yet for this week, fall back to last week
    # so the UI is never empty. Will be replaced on the Monday run.
    fell_back = False
    if not rows:
        prior_week = week_start - timedelta(days=7)
        rows = db.execute(
            select(WeeklyGaugeSelection)
            .where(WeeklyGaugeSelection.iso_week_start == prior_week)
            .order_by(WeeklyGaugeSelection.rank)
        ).scalars().all()
        if rows:
            fell_back = True

    # Filter out anchor gauges — they're rendered as fixed anchors in
    # the hero (revenue / fleet / cook success). Legacy week-rows may
    # still contain anchor picks; drop them at serve time so the UI
    # never shows a duplicate.
    rows = [r for r in rows if r.metric_key not in ANCHOR_KEYS]
    gauges = [_serialize_gauge(db, r) for r in rows]
    theme = None
    if rows and rows[0].selection_context_json:
        theme = rows[0].selection_context_json.get("overall_theme")

    return {
        "week_start": week_start.isoformat(),
        "overall_theme": theme,
        "fell_back_to_prior_week": fell_back,
        "gauges": gauges,
    }


@router.post("/weekly-gauges/regenerate")
def regenerate_weekly_gauges(
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Owner-only manual trigger. Forces a fresh Opus pick for the
    current week, preserving any pinned gauges from prior weeks."""
    user = get_user_from_request(request, db)
    if user is None or (user.email or "").lower() != "joseph@spidergrills.com":
        raise HTTPException(status_code=403, detail="Owner only")
    result = run_weekly_gauge_selection(db, force=True)
    return result


@router.patch("/weekly-gauges/{rank}/pin")
def pin_weekly_gauge(
    rank: int,
    pinned: bool,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Owner-only. Pin or unpin a gauge so it carries forward next week."""
    user = get_user_from_request(request, db)
    if user is None or (user.email or "").lower() != "joseph@spidergrills.com":
        raise HTTPException(status_code=403, detail="Owner only")
    if rank < 1 or rank > 20:
        raise HTTPException(status_code=400, detail="Invalid rank")
    week_start = _iso_week_start(date.today())
    row = db.execute(
        select(WeeklyGaugeSelection).where(
            WeeklyGaugeSelection.iso_week_start == week_start,
            WeeklyGaugeSelection.rank == rank,
        )
    ).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Gauge not found")
    row.pinned = bool(pinned)
    db.commit()
    return {"rank": row.rank, "metric_key": row.metric_key, "pinned": row.pinned}
