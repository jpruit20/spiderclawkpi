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
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_dashboard_session
from app.models import LoreEvent
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


# ---------------------------------------------------------------------------
# Event Timeline — institutional memory of business events
# ---------------------------------------------------------------------------

# Kept as a loose constant (not an Enum) so new event types don't require
# code changes — frontend can send whatever string Joseph finds useful.
KNOWN_EVENT_TYPES = {
    "launch", "incident", "campaign", "promotion", "firmware",
    "hardware_revision", "personnel", "press", "external", "holiday", "other",
}
KNOWN_CONFIDENCES = {"confirmed", "inferred", "rumored"}


class EventCreate(BaseModel):
    event_type: str = Field(..., min_length=1, max_length=32)
    title: str = Field(..., min_length=1, max_length=256)
    description: Optional[str] = None
    start_date: date
    end_date: Optional[date] = None
    division: Optional[str] = None
    confidence: str = "confirmed"
    source_type: str = "manual"
    source_refs: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventUpdate(BaseModel):
    event_type: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    division: Optional[str] = None
    confidence: Optional[str] = None
    source_type: Optional[str] = None
    source_refs: Optional[dict[str, Any]] = None
    metadata: Optional[dict[str, Any]] = None


def _serialize_event(ev: LoreEvent) -> dict[str, Any]:
    return {
        "id": ev.id,
        "event_type": ev.event_type,
        "title": ev.title,
        "description": ev.description,
        "start_date": ev.start_date.isoformat() if ev.start_date else None,
        "end_date": ev.end_date.isoformat() if ev.end_date else None,
        "division": ev.division,
        "confidence": ev.confidence,
        "source_type": ev.source_type,
        "source_refs": ev.source_refs_json or {},
        "metadata": ev.metadata_json or {},
        "created_by": ev.created_by,
        "created_at": ev.created_at.isoformat() if ev.created_at else None,
        "updated_at": ev.updated_at.isoformat() if ev.updated_at else None,
    }


def _validate_event_fields(event_type: Optional[str], confidence: Optional[str]) -> None:
    # Allow unknown types/confidences through but warn — better than rejecting
    # Joseph's mid-design brainstorm with a 400.
    if event_type and event_type not in KNOWN_EVENT_TYPES:
        logger.info("lore_event: unknown event_type=%s (allowing)", event_type)
    if confidence and confidence not in KNOWN_CONFIDENCES:
        raise HTTPException(
            status_code=400,
            detail=f"invalid confidence: {confidence} (expected one of {sorted(KNOWN_CONFIDENCES)})",
        )


@router.get("/events")
def list_events(
    start: Optional[str] = Query(None, description="YYYY-MM-DD — only return events overlapping >= this date"),
    end: Optional[str] = Query(None, description="YYYY-MM-DD — only return events overlapping <= this date"),
    division: Optional[str] = Query(None, description="filter by division (or 'company' for division IS NULL)"),
    event_type: Optional[str] = Query(None, description="filter by event_type"),
    confidence: Optional[str] = Query(None, description="filter by confidence"),
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """List events, optionally scoped to a date range and/or division.

    Overlap semantics: an event [s, e] (or single-day if e is NULL) is
    "in range" for [start, end] iff s <= end AND (e >= start OR e IS NULL
    AND s >= start). In plain English: the event's span intersects
    the query window.
    """
    q = select(LoreEvent)

    if start:
        start_d = _parse_iso_date(start, "start")
        # event's end_date is >= start, OR event is single-day (end_date NULL)
        # and start_date >= query.start.
        q = q.where(
            or_(
                LoreEvent.end_date >= start_d,
                and_(LoreEvent.end_date.is_(None), LoreEvent.start_date >= start_d),
            )
        )
    if end:
        end_d = _parse_iso_date(end, "end")
        q = q.where(LoreEvent.start_date <= end_d)
    if division is not None:
        if division == "company":
            q = q.where(LoreEvent.division.is_(None))
        else:
            q = q.where(LoreEvent.division == division)
    if event_type:
        q = q.where(LoreEvent.event_type == event_type)
    if confidence:
        q = q.where(LoreEvent.confidence == confidence)

    q = q.order_by(LoreEvent.start_date.asc()).limit(limit)
    rows = db.execute(q).scalars().all()

    return {
        "events": [_serialize_event(ev) for ev in rows],
        "count": len(rows),
    }


@router.get("/events/{event_id}")
def get_event(event_id: int, db: Session = Depends(db_session)) -> dict[str, Any]:
    ev = db.get(LoreEvent, event_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="event not found")
    return _serialize_event(ev)


@router.post("/events", status_code=201)
def create_event(body: EventCreate, db: Session = Depends(db_session)) -> dict[str, Any]:
    _validate_event_fields(body.event_type, body.confidence)
    if body.end_date and body.end_date < body.start_date:
        raise HTTPException(status_code=400, detail="end_date must be >= start_date")

    ev = LoreEvent(
        event_type=body.event_type,
        title=body.title,
        description=body.description,
        start_date=body.start_date,
        end_date=body.end_date,
        division=body.division,
        confidence=body.confidence,
        source_type=body.source_type,
        source_refs_json=body.source_refs or {},
        metadata_json=body.metadata or {},
    )
    db.add(ev)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        # Likely the (title, start_date) unique constraint.
        raise HTTPException(status_code=409, detail=f"event conflicts with existing: {e}")
    db.refresh(ev)
    return _serialize_event(ev)


@router.patch("/events/{event_id}")
def update_event(
    event_id: int,
    body: EventUpdate,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    ev = db.get(LoreEvent, event_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="event not found")

    _validate_event_fields(body.event_type, body.confidence)

    data = body.model_dump(exclude_unset=True)
    if "source_refs" in data:
        ev.source_refs_json = data.pop("source_refs") or {}
    if "metadata" in data:
        ev.metadata_json = data.pop("metadata") or {}
    for key, val in data.items():
        setattr(ev, key, val)

    # Re-validate date span after applying updates.
    if ev.end_date and ev.start_date and ev.end_date < ev.start_date:
        db.rollback()
        raise HTTPException(status_code=400, detail="end_date must be >= start_date")

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"update conflict: {e}")
    db.refresh(ev)
    return _serialize_event(ev)


@router.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: int, db: Session = Depends(db_session)) -> None:
    ev = db.get(LoreEvent, event_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="event not found")
    db.delete(ev)
    db.commit()
    return None


@router.get("/events/stats/summary")
def event_stats(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Counts by event_type / confidence / division — for a summary widget
    on the Executive Overview or the lore admin page."""
    q = select(LoreEvent)
    if start:
        q = q.where(LoreEvent.start_date >= _parse_iso_date(start, "start"))
    if end:
        q = q.where(LoreEvent.start_date <= _parse_iso_date(end, "end"))
    rows = db.execute(q).scalars().all()

    by_type: dict[str, int] = {}
    by_confidence: dict[str, int] = {}
    by_division: dict[str, int] = {}
    for ev in rows:
        by_type[ev.event_type] = by_type.get(ev.event_type, 0) + 1
        by_confidence[ev.confidence] = by_confidence.get(ev.confidence, 0) + 1
        key = ev.division or "company"
        by_division[key] = by_division.get(key, 0) + 1

    return {
        "total": len(rows),
        "by_type": by_type,
        "by_confidence": by_confidence,
        "by_division": by_division,
    }
