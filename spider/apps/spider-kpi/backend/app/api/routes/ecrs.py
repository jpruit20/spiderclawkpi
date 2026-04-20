"""Engineering Change Request (ECR) tracker.

Source of truth: ClickUp. An ECR is any ``ClickUpTask`` whose ``Category``
custom field equals ``ECR``. This route filters the already-synced task
table — it does not talk to ClickUp directly.

Access is owner-gated while the surface is still being shaped. The UI
route uses the same pattern as Lore Ledger (``OwnerOnlyRoute`` in
App.tsx); here we repeat the check on the backend so the API cannot be
bypassed from the browser.

ECR custom fields expected on the ClickUp task (Joseph is adding these
2026-04-20):

  * ``Category`` (dropdown, value=ECR)
  * ``Impact Areas`` (multi-select: CX, Operations, Manufacturing, Product Engineering)
  * ``Dev Complete`` (date)
  * ``Production Ready`` (date)
  * ``Field Deploy`` (date)
  * ``CX Talking Points`` (text — customer-facing framing)
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.api.routes.auth import get_user_from_request
from app.models import ClickUpTask
from app.services.clickup_fields import (
    get_date,
    get_dropdown_label,
    get_multi_select_labels,
    get_text,
)


logger = logging.getLogger(__name__)

OWNER_EMAIL = "joseph@spidergrills.com"
CATEGORY_FIELD = "Category"
CATEGORY_VALUE = "ECR"
IMPACT_AREAS_FIELD = "Impact Areas"
DEV_COMPLETE_FIELD = "Dev Complete"
PRODUCTION_READY_FIELD = "Production Ready"
FIELD_DEPLOY_FIELD = "Field Deploy"
CX_TALKING_POINTS_FIELD = "CX Talking Points"


def _require_owner(request: Request, db: Session = Depends(db_session)) -> None:
    user = get_user_from_request(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Dashboard session required")
    if (user.email or "").lower() != OWNER_EMAIL:
        raise HTTPException(status_code=403, detail="ECR tracker is owner-only while in preview")


router = APIRouter(prefix="/api/ecrs", tags=["ecrs"], dependencies=[Depends(_require_owner)])


def _serialize(task: ClickUpTask) -> dict[str, Any]:
    impact = get_multi_select_labels(task, IMPACT_AREAS_FIELD)
    dev_complete = get_date(task, DEV_COMPLETE_FIELD)
    production_ready = get_date(task, PRODUCTION_READY_FIELD)
    field_deploy = get_date(task, FIELD_DEPLOY_FIELD)
    talking_points = get_text(task, CX_TALKING_POINTS_FIELD)

    # ClickUp URL convention: https://app.clickup.com/t/<task_id>
    # The raw payload holds the canonical URL when available.
    url = None
    raw = getattr(task, "raw_payload", None)
    if isinstance(raw, dict):
        url = raw.get("url")
    if not url and task.task_id:
        url = f"https://app.clickup.com/t/{task.task_id}"

    return {
        "task_id": task.task_id,
        "custom_id": task.custom_id,
        "name": task.name,
        "description": task.description,
        "status": task.status,
        "status_type": task.status_type,
        "priority": task.priority,
        "space_name": task.space_name,
        "list_name": task.list_name,
        "folder_name": task.folder_name,
        "creator_username": task.creator_username,
        "assignees": [
            a.get("username") or a.get("email") or a.get("id")
            for a in (task.assignees_json or []) if isinstance(a, dict)
        ],
        "url": url,
        "impact_areas": impact,
        "dev_complete": dev_complete.isoformat() if dev_complete else None,
        "production_ready": production_ready.isoformat() if production_ready else None,
        "field_deploy": field_deploy.isoformat() if field_deploy else None,
        "cx_talking_points": talking_points,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


def _is_ecr(task: ClickUpTask) -> bool:
    label = get_dropdown_label(task, CATEGORY_FIELD)
    return bool(label) and label.strip().lower() == CATEGORY_VALUE.lower()


@router.get("")
def list_ecrs(
    include_closed: bool = False,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Return every ClickUp task tagged Category=ECR. By default closed
    / done tasks are hidden; pass ``include_closed=true`` to see the
    full archive."""
    stmt = select(ClickUpTask).order_by(desc(ClickUpTask.updated_at))
    if not include_closed:
        # status_type is one of 'open' | 'closed' | 'done' | 'custom'. We
        # keep 'custom' because ClickUp maps a lot of in-flight statuses
        # (in review, testing, blocked) to it.
        stmt = stmt.where(ClickUpTask.status_type.in_(("open", "custom")))
    rows = db.execute(stmt).scalars().all()
    ecrs = [_serialize(t) for t in rows if _is_ecr(t)]
    # Group status into a handful of pipeline buckets so the UI can show
    # a consistent progress strip regardless of how the ClickUp workflow
    # is configured. Everything unknown lands in 'other'.
    pipeline_buckets = {
        "backlog": ["backlog", "open", "to do", "todo"],
        "in_review": ["in review", "review", "design review"],
        "approved": ["approved", "ready"],
        "in_progress": ["in progress", "doing", "development", "dev"],
        "testing": ["testing", "qa", "in qa"],
        "deploying": ["deploying", "deploy", "staged", "production"],
        "deployed": ["deployed", "done", "complete", "closed", "shipped"],
    }
    for e in ecrs:
        s = (e.get("status") or "").lower().strip()
        stage = "other"
        for bucket, aliases in pipeline_buckets.items():
            if s in aliases:
                stage = bucket
                break
        e["pipeline_stage"] = stage
    return {
        "ecrs": ecrs,
        "count": len(ecrs),
        "fields_expected": [
            CATEGORY_FIELD, IMPACT_AREAS_FIELD, DEV_COMPLETE_FIELD,
            PRODUCTION_READY_FIELD, FIELD_DEPLOY_FIELD, CX_TALKING_POINTS_FIELD,
        ],
    }
