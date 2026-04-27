"""KPI Targets API.

Operator UI on the Command Center reads/writes against these endpoints
to set seasonal targets per metric. Targets feed back into
``/api/trends/all`` so the snapshot tiles can color themselves
green/red based on hit-vs-miss.
"""
from __future__ import annotations

from datetime import date as _date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_auth
from app.services.kpi_targets import (
    delete_target,
    get_active_targets,
    list_targets,
    upsert_target,
)


router = APIRouter(prefix="/api/kpi-targets", tags=["kpi-targets"])


class TargetIn(BaseModel):
    id: Optional[int] = None  # set to update; omit/null to create
    metric_key: str
    target_value: float
    direction: str = "min"  # "min" = at-or-above is good; "max" = at-or-below is good
    effective_start: Optional[str] = None  # YYYY-MM-DD
    effective_end: Optional[str] = None
    season_label: Optional[str] = None
    notes: Optional[str] = None


@router.get("")
def list_(
    metric_key: Optional[str] = Query(None),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    return {"targets": list_targets(db, metric_key=metric_key)}


@router.get("/active")
def active(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Active target per metric for today, narrowest-window-wins."""
    return {"active": get_active_targets(db)}


@router.post("", dependencies=[Depends(require_auth)])
def upsert(
    payload: TargetIn,
    request: Request,
    db: Session = Depends(db_session),
    user: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    user_email = (user or {}).get("email") if isinstance(user, dict) else None
    s = _date.fromisoformat(payload.effective_start) if payload.effective_start else None
    e = _date.fromisoformat(payload.effective_end) if payload.effective_end else None
    if s is not None and e is not None and e <= s:
        raise HTTPException(status_code=400, detail="effective_end must be after effective_start")
    if payload.direction not in ("min", "max"):
        raise HTTPException(status_code=400, detail="direction must be 'min' or 'max'")
    row = upsert_target(
        db,
        metric_key=payload.metric_key,
        target_value=payload.target_value,
        direction=payload.direction,
        effective_start=s,
        effective_end=e,
        season_label=payload.season_label,
        notes=payload.notes,
        user=user_email,
        target_id=payload.id,
    )
    return {
        "ok": True,
        "id": row.id,
        "metric_key": row.metric_key,
        "target_value": float(row.target_value),
        "direction": row.direction,
        "effective_start": row.effective_start.isoformat() if row.effective_start else None,
        "effective_end": row.effective_end.isoformat() if row.effective_end else None,
        "season_label": row.season_label,
    }


@router.delete("/{target_id}", dependencies=[Depends(require_auth)])
def delete_(
    target_id: int,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    ok = delete_target(db, target_id=target_id)
    if not ok:
        raise HTTPException(status_code=404, detail="not found")
    return {"ok": True, "deleted_id": target_id}
