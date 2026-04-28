"""KPI Targets API.

Permissions model:
- Joseph (joseph@spidergrills.com) can read+edit any target, any division.
- Each division lead can read+edit only targets in their division:
    bailey  → marketing
    jeremiah → cx
    conor    → operations
    kyle     → pe
    david    → manufacturing
- division=NULL targets are "global" (Command Center) and only Joseph
  can edit them. Anyone authenticated can read them.

GET /api/kpi-targets?division=marketing  — list per-division
GET /api/kpi-targets/active                — current effective targets
GET /api/kpi-targets/permissions           — what *I* can edit
POST /api/kpi-targets                     — auth-checked create/update
DELETE /api/kpi-targets/{id}              — auth-checked
"""
from __future__ import annotations

from datetime import date as _date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_auth, require_dashboard_or_service_token
from app.api.routes.auth import get_user_from_request
from app.services.division_ownership import (
    DIVISION_OWNERS,
    can_edit_division,
    division_label,
    editable_divisions_for,
    is_platform_owner,
)
from app.services.kpi_targets import (
    delete_target,
    get_active_targets,
    list_targets,
    upsert_target,
)
from app.models import KpiTarget
from sqlalchemy import select


router = APIRouter(prefix="/api/kpi-targets", tags=["kpi-targets"])


class TargetIn(BaseModel):
    id: Optional[int] = None
    metric_key: str
    target_value: float
    direction: str = "min"
    effective_start: Optional[str] = None
    effective_end: Optional[str] = None
    season_label: Optional[str] = None
    notes: Optional[str] = None
    division: Optional[str] = None  # null = global; only Joseph can set/edit


def _email_from_request(request: Request, db: Session) -> Optional[str]:
    """Resolve the calling user's email from a dashboard session cookie.

    require_dashboard_or_service_token already validated the cookie or the
    X-App-Password header on the way in. If the request came in via cookie,
    we can pull the user; via service token there's no user (returns None,
    callers fall back to platform-owner-equivalent behavior since the
    service token IS admin-equivalent).
    """
    user = get_user_from_request(request, db)
    if user is None:
        return None
    return (user.email or "").lower() or None


def _user_email(user: Any) -> Optional[str]:
    """Legacy shim — kept so any existing callers passing a dict still work."""
    if isinstance(user, dict):
        return (user.get("email") or "").lower() or None
    return None


@router.get("")
def list_(
    metric_key: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    include_global: bool = Query(True, description="When filtering by division, also include global (NULL) targets"),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    return {"targets": list_targets(db, metric_key=metric_key, division=division, include_global=include_global)}


@router.get("/active")
def active(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Active target per metric for today, narrowest-window-wins."""
    return {"active": get_active_targets(db)}


@router.get("/permissions")
def permissions(
    request: Request,
    db: Session = Depends(db_session),
    _: None = Depends(require_dashboard_or_service_token),
) -> dict[str, Any]:
    """What can the calling user edit? Frontend uses this to gate
    the 'Set targets' button + the Save action.

    Auth: accepts dashboard session cookie OR X-App-Password. The
    earlier `require_auth` (X-App-Password only) caused the
    Command Center 'Set targets' panel to silently 401 from the
    browser, leaving the panel read-only — fixed 2026-04-28.
    """
    email = _email_from_request(request, db)
    divs = editable_divisions_for(email)
    return {
        "user_email": email,
        "is_platform_owner": is_platform_owner(email),
        "editable_divisions": [
            {"code": d, "label": division_label(d)} for d in divs
        ],
        "division_owners": [
            {"division": d, "label": division_label(d), "owner_email": e}
            for d, e in DIVISION_OWNERS.items()
        ],
    }


@router.post("")
def upsert(
    payload: TargetIn,
    request: Request,
    db: Session = Depends(db_session),
    _: None = Depends(require_dashboard_or_service_token),
) -> dict[str, Any]:
    user_email = _email_from_request(request, db)
    if not can_edit_division(user_email, payload.division):
        raise HTTPException(
            status_code=403,
            detail=(
                f"User {user_email} cannot edit targets for division {payload.division!r}. "
                f"Division leads can only edit their own division; global (null) targets are platform-owner-only."
            ),
        )
    # If editing existing target, also check we own its current division
    if payload.id is not None:
        existing = db.get(KpiTarget, payload.id)
        if existing is None:
            raise HTTPException(status_code=404, detail="target not found")
        if not can_edit_division(user_email, existing.division):
            raise HTTPException(
                status_code=403,
                detail=f"Cannot move target out of division {existing.division!r}",
            )

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
        division=payload.division,
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
        "division": row.division,
        "owner_email": row.owner_email,
    }


@router.delete("/{target_id}")
def delete_(
    target_id: int,
    request: Request,
    db: Session = Depends(db_session),
    _: None = Depends(require_dashboard_or_service_token),
) -> dict[str, Any]:
    user_email = _email_from_request(request, db)
    existing = db.get(KpiTarget, target_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="not found")
    if not can_edit_division(user_email, existing.division):
        raise HTTPException(
            status_code=403,
            detail=f"User {user_email} cannot delete targets in division {existing.division!r}",
        )
    delete_target(db, target_id=target_id)
    return {"ok": True, "deleted_id": target_id}
