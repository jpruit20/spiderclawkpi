"""Per-division page configuration API.

Each division lead can edit their own division's layout (card order,
visibility, titles, default windows). Joseph (platform owner) can
edit any. Read-only fallback for everyone else.

The frontend calls these on division-page mount to apply the active
operator's preferred layout. Changes are audit-logged so Joseph can
review + revert.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_auth
from app.models import PageConfig
from app.services.division_ownership import (
    DIVISION_OWNERS,
    can_edit_division,
    is_platform_owner,
)


router = APIRouter(prefix="/api/page-configs", tags=["page-configs"])


def _user_email(user: Any) -> Optional[str]:
    if isinstance(user, dict):
        return (user.get("email") or "").lower() or None
    return None


def _resolve_owner(division: str) -> Optional[str]:
    """The canonical owner email for a division — used when no user
    has saved a config yet so we read the lead's row by default."""
    return DIVISION_OWNERS.get(division)


@router.get("/{division}")
def get_config(
    division: str,
    db: Session = Depends(db_session),
    user: Any = Depends(require_auth),
) -> dict[str, Any]:
    """Returns the active config for a division. If the calling user
    is the division lead, returns their row. Otherwise returns the
    lead's row (so everyone sees the operator's chosen layout)."""
    user_email = _user_email(user)
    owner = DIVISION_OWNERS.get(division)
    if owner is None and not is_platform_owner(user_email):
        raise HTTPException(status_code=400, detail=f"Unknown division: {division}")

    target_email = owner or user_email or ""
    row = db.execute(
        select(PageConfig).where(
            PageConfig.division == division,
            PageConfig.owner_email == target_email,
        )
    ).scalar_one_or_none()
    return {
        "division": division,
        "owner_email": target_email,
        "config_json": row.config_json if row else {},
        "exists": row is not None,
        "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
        "updated_by": row.updated_by if row else None,
        "can_edit": can_edit_division(user_email, division),
        "audit_log": (row.audit_log_json[-20:] if row and row.audit_log_json else []),
    }


class PageConfigUpsertIn(BaseModel):
    config_json: dict[str, Any]
    change_summary: Optional[str] = Field(default=None, description="Short human-readable description of what changed")


@router.post("/{division}")
def upsert_config(
    division: str,
    payload: PageConfigUpsertIn,
    db: Session = Depends(db_session),
    user: Any = Depends(require_auth),
) -> dict[str, Any]:
    user_email = _user_email(user)
    if not can_edit_division(user_email, division):
        raise HTTPException(
            status_code=403,
            detail=f"User {user_email} cannot edit page config for division {division!r}",
        )

    owner = DIVISION_OWNERS.get(division) or user_email or ""
    row = db.execute(
        select(PageConfig).where(
            PageConfig.division == division,
            PageConfig.owner_email == owner,
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None:
        row = PageConfig(
            division=division,
            owner_email=owner,
            config_json=payload.config_json,
            audit_log_json=[],
            updated_by=user_email,
        )
        db.add(row)
    else:
        # Append audit entry capturing what changed
        audit_entry = {
            "at": now.isoformat(),
            "by": user_email,
            "change_summary": (payload.change_summary or "config update")[:200],
        }
        existing_log = list(row.audit_log_json or [])
        existing_log.append(audit_entry)
        # Keep audit log bounded
        row.audit_log_json = existing_log[-100:]
        row.config_json = payload.config_json
        row.updated_by = user_email
        row.updated_at = now
    db.commit()
    db.refresh(row)
    return {
        "ok": True,
        "division": division,
        "owner_email": row.owner_email,
        "config_json": row.config_json,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "updated_by": row.updated_by,
    }


@router.delete("/{division}")
def reset_config(
    division: str,
    db: Session = Depends(db_session),
    user: Any = Depends(require_auth),
) -> dict[str, Any]:
    """Reset to defaults. Only the platform owner OR the division
    lead can do this. Wipes config_json but keeps audit log."""
    user_email = _user_email(user)
    if not can_edit_division(user_email, division):
        raise HTTPException(status_code=403, detail="Forbidden")
    owner = DIVISION_OWNERS.get(division)
    if owner is None:
        raise HTTPException(status_code=400, detail=f"Unknown division: {division}")
    row = db.execute(
        select(PageConfig).where(
            PageConfig.division == division,
            PageConfig.owner_email == owner,
        )
    ).scalar_one_or_none()
    if row is None:
        return {"ok": True, "reset": "no-op (no config existed)"}
    audit_entry = {
        "at": datetime.now(timezone.utc).isoformat(),
        "by": user_email,
        "change_summary": "RESET to defaults",
    }
    existing_log = list(row.audit_log_json or [])
    existing_log.append(audit_entry)
    row.audit_log_json = existing_log[-100:]
    row.config_json = {}
    row.updated_by = user_email
    db.commit()
    return {"ok": True, "reset": True}
