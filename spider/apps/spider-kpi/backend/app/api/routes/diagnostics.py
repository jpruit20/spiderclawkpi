"""Diagnostics API — receives app-emitted events, replaces [AUTOMATED] tickets.

POST /api/diagnostics/event  — called by the Venom app when a
diagnostic fires. No auth — this is a device endpoint (the app can't
carry a dashboard session). If/when we need auth, we'll gate by a
shared HMAC or API-key header.

GET /api/diagnostics/events  — dashboard-auth, returns recent events
with filters for the Firmware Hub card.

POST /api/diagnostics/event/{id}/resolve  — dashboard-auth; marks
an event resolved with a note.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_dashboard_session
from app.models import DiagnosticEvent


public_router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])
router = APIRouter(
    prefix="/api/diagnostics",
    tags=["diagnostics"],
    dependencies=[Depends(require_dashboard_session)],
)


class DiagnosticEventIn(BaseModel):
    event_type: str = Field(max_length=64, description="Short slug, e.g. 'wifi_provisioning_fail' or 'controller_crash'")
    severity: str = Field(default="info", description="info | warning | error | critical")
    mac: Optional[str] = Field(default=None, max_length=12)
    device_id: Optional[str] = None
    user_id: Optional[str] = None
    firmware_version: Optional[str] = None
    app_version: Optional[str] = None
    platform: Optional[str] = None
    title: Optional[str] = Field(default=None, max_length=256)
    details: dict[str, Any] = Field(default_factory=dict)


@public_router.post("/event")
def ingest_event(payload: DiagnosticEventIn, db: Session = Depends(db_session)) -> dict[str, Any]:
    """No-auth endpoint the Venom app posts to when a diagnostic fires.

    Returns the created event id so the app can link back if the user
    escalates the diagnostic to a real support ticket later.
    """
    if payload.severity not in {"info", "warning", "error", "critical"}:
        raise HTTPException(status_code=400, detail="severity must be info | warning | error | critical")
    row = DiagnosticEvent(
        event_type=payload.event_type,
        severity=payload.severity,
        mac=(payload.mac or "").lower().replace(":", "").replace("-", "") or None,
        device_id=payload.device_id,
        user_id=payload.user_id,
        firmware_version=payload.firmware_version,
        app_version=payload.app_version,
        platform=payload.platform,
        title=payload.title,
        details_json=payload.details or {},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "event_type": row.event_type, "created_at": row.created_at.isoformat()}


@router.get("/events")
def list_events(
    days: int = Query(7, ge=1, le=90),
    event_type: Optional[str] = None,
    severity: Optional[str] = None,
    include_resolved: bool = False,
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = select(DiagnosticEvent).where(DiagnosticEvent.created_at >= since).order_by(desc(DiagnosticEvent.created_at))
    if event_type:
        q = q.where(DiagnosticEvent.event_type == event_type)
    if severity:
        q = q.where(DiagnosticEvent.severity == severity)
    if not include_resolved:
        q = q.where(DiagnosticEvent.resolved_at.is_(None))
    rows = db.execute(q.limit(limit)).scalars().all()

    # Aggregates for the summary strip
    summary = db.execute(
        select(
            DiagnosticEvent.event_type,
            DiagnosticEvent.severity,
            func.count(DiagnosticEvent.id),
        )
        .where(DiagnosticEvent.created_at >= since)
        .group_by(DiagnosticEvent.event_type, DiagnosticEvent.severity)
        .order_by(desc(func.count(DiagnosticEvent.id)))
    ).all()
    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for et, sev, n in summary:
        by_type[et] = by_type.get(et, 0) + int(n)
        by_severity[sev or "info"] = by_severity.get(sev or "info", 0) + int(n)
    total_in_window = sum(by_type.values())
    total_open = db.execute(
        select(func.count(DiagnosticEvent.id))
        .where(DiagnosticEvent.created_at >= since, DiagnosticEvent.resolved_at.is_(None))
    ).scalar() or 0

    return {
        "window_days": days,
        "total_in_window": total_in_window,
        "total_open": total_open,
        "by_type": by_type,
        "by_severity": by_severity,
        "events": [
            {
                "id": r.id,
                "event_type": r.event_type,
                "severity": r.severity,
                "mac": r.mac,
                "device_id": r.device_id,
                "user_id": r.user_id,
                "firmware_version": r.firmware_version,
                "app_version": r.app_version,
                "platform": r.platform,
                "title": r.title,
                "details": r.details_json,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
                "resolved_by": r.resolved_by,
                "resolution_note": r.resolution_note,
            }
            for r in rows
        ],
    }


class ResolveIn(BaseModel):
    note: Optional[str] = None
    resolved_by: Optional[str] = None


@router.post("/event/{event_id}/resolve")
def resolve_event(event_id: int, payload: ResolveIn = Body(...), db: Session = Depends(db_session)) -> dict[str, Any]:
    row = db.execute(select(DiagnosticEvent).where(DiagnosticEvent.id == event_id)).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="event not found")
    if row.resolved_at is None:
        row.resolved_at = datetime.now(timezone.utc)
    row.resolution_note = payload.note
    row.resolved_by = payload.resolved_by
    db.commit()
    return {"id": row.id, "resolved_at": row.resolved_at.isoformat(), "resolved_by": row.resolved_by}
