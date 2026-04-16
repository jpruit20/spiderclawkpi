"""ClickUp API routes.

Two surfaces:

  * ``GET  /api/clickup/tasks`` — generic filterable task listing consumed by
    the reusable ``<ClickUpTasksCard>`` on Customer Experience, Operations,
    Marketing, and Product/Engineering pages.
  * ``GET  /api/clickup/spaces`` — discovery helper so each page can pick a
    default filter.
  * ``POST /api/clickup/deci/{decision_id}/sync`` — create a ClickUp task from
    a DECI decision, store the returned task_id on the decision.
  * ``POST /api/clickup/deci/{decision_id}/refresh`` — pull latest status +
    comments from ClickUp, cache on the decision, auto-log status changes.
  * ``POST /api/clickup/deci/{decision_id}/unlink`` — detach without deleting
    the ClickUp task.
  * ``POST /api/clickup/sync-now`` — admin-triggered full sync (mostly for
    first-run / manual refresh).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, desc, or_, select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_dashboard_session
from app.core.config import get_settings
from app.ingestion.connectors.clickup import (
    add_task_comment,
    create_task_in_list,
    fetch_task,
    fetch_task_comments,
    list_spaces,
    sync_clickup,
)
from app.models import (
    ClickUpTask,
    DeciDecision,
    DeciDecisionLog,
)


router = APIRouter(
    prefix="/api/clickup",
    tags=["clickup"],
    dependencies=[Depends(require_dashboard_session)],
)

settings = get_settings()


def _task_to_dict(t: ClickUpTask) -> dict[str, Any]:
    return {
        "task_id": t.task_id,
        "custom_id": t.custom_id,
        "name": t.name,
        "status": t.status,
        "status_type": t.status_type,
        "priority": t.priority,
        "space_id": t.space_id,
        "space_name": t.space_name,
        "folder_id": t.folder_id,
        "folder_name": t.folder_name,
        "list_id": t.list_id,
        "list_name": t.list_name,
        "assignees": t.assignees_json or [],
        "tags": t.tags_json or [],
        "url": t.url,
        "date_created": t.date_created.isoformat() if t.date_created else None,
        "date_updated": t.date_updated.isoformat() if t.date_updated else None,
        "date_done": t.date_done.isoformat() if t.date_done else None,
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "archived": t.archived,
        "is_open": (t.status_type or "").lower() != "closed" and not t.archived,
    }


@router.get("/config")
def get_config() -> dict[str, Any]:
    return {
        "configured": bool(settings.clickup_api_token and settings.clickup_team_id),
        "team_id": settings.clickup_team_id,
        "base_url": settings.clickup_base_url,
    }


@router.get("/spaces")
def get_spaces(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Return spaces either from live API (if configured) or distinct from DB."""
    if settings.clickup_api_token and settings.clickup_team_id:
        try:
            spaces = list_spaces()
            return {"source": "live", "spaces": [
                {"id": s["id"], "name": s["name"], "private": s.get("private", False)}
                for s in spaces
            ]}
        except Exception as exc:
            # Fall through to DB-only view if the live call fails.
            pass
    rows = db.execute(
        select(ClickUpTask.space_id, ClickUpTask.space_name).distinct()
    ).all()
    return {
        "source": "db",
        "spaces": [{"id": r[0], "name": r[1], "private": False} for r in rows if r[0]],
    }


@router.get("/lists")
def get_lists(space_id: Optional[str] = None, db: Session = Depends(db_session)) -> dict[str, Any]:
    """Distinct list metadata derived from already-synced tasks.

    Used by the DECI "Also create in ClickUp" dropdown. If no tasks have been
    synced yet for a space, the dropdown will be empty — trigger a manual
    sync via ``POST /api/clickup/sync-now`` or wait for the scheduler.
    """
    stmt = select(
        ClickUpTask.list_id,
        ClickUpTask.list_name,
        ClickUpTask.space_id,
        ClickUpTask.space_name,
        ClickUpTask.folder_name,
    ).distinct()
    if space_id:
        stmt = stmt.where(ClickUpTask.space_id == space_id)
    rows = db.execute(stmt).all()
    return {
        "lists": [
            {
                "list_id": r[0],
                "list_name": r[1],
                "space_id": r[2],
                "space_name": r[3],
                "folder_name": r[4],
            }
            for r in rows if r[0]
        ]
    }


@router.get("/tasks")
def list_tasks(
    space_id: Optional[str] = None,
    list_id: Optional[str] = None,
    folder_id: Optional[str] = None,
    status_type: Optional[str] = None,   # 'open' | 'closed' | 'done'
    priority: Optional[str] = None,
    assignee: Optional[str] = None,       # username or email substring
    due_within_days: Optional[int] = None,  # overdue if negative, upcoming if positive
    overdue_only: bool = False,
    q: Optional[str] = None,              # substring search on name
    limit: int = 50,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    limit = max(1, min(limit, 500))
    stmt = select(ClickUpTask)
    filters = []
    if space_id:
        filters.append(ClickUpTask.space_id == space_id)
    if list_id:
        filters.append(ClickUpTask.list_id == list_id)
    if folder_id:
        filters.append(ClickUpTask.folder_id == folder_id)
    if status_type:
        st = status_type.lower()
        if st == "open":
            filters.append(and_(
                ClickUpTask.archived == False,  # noqa: E712
                or_(ClickUpTask.status_type.is_(None), ClickUpTask.status_type != "closed"),
            ))
        else:
            filters.append(ClickUpTask.status_type == st)
    if priority:
        filters.append(ClickUpTask.priority == priority)
    if q:
        filters.append(ClickUpTask.name.ilike(f"%{q}%"))
    now = datetime.now(timezone.utc)
    if overdue_only:
        filters.append(and_(
            ClickUpTask.due_date.isnot(None),
            ClickUpTask.due_date < now,
            or_(ClickUpTask.status_type.is_(None), ClickUpTask.status_type != "closed"),
        ))
    if due_within_days is not None:
        if due_within_days >= 0:
            filters.append(and_(
                ClickUpTask.due_date.isnot(None),
                ClickUpTask.due_date <= now + timedelta(days=due_within_days),
            ))
        else:
            filters.append(and_(
                ClickUpTask.due_date.isnot(None),
                ClickUpTask.due_date >= now + timedelta(days=due_within_days),
            ))

    if filters:
        stmt = stmt.where(and_(*filters))
    stmt = stmt.order_by(desc(ClickUpTask.date_updated)).limit(limit)
    rows = db.execute(stmt).scalars().all()

    tasks = [_task_to_dict(t) for t in rows]

    if assignee:
        needle = assignee.strip().lower()
        tasks = [t for t in tasks if any(
            (a.get("username") or "").lower().find(needle) >= 0
            or (a.get("email") or "").lower().find(needle) >= 0
            for a in t["assignees"]
        )]

    # Small aggregate to render "x open · y overdue" headline on the card.
    summary = {
        "total": len(tasks),
        "open": sum(1 for t in tasks if t["is_open"]),
        "overdue": sum(1 for t in tasks if t["due_date"] and t["is_open"] and datetime.fromisoformat(t["due_date"]) < now),
        "by_status": {},
        "by_priority": {},
    }
    for t in tasks:
        if t["status"]:
            summary["by_status"][t["status"]] = summary["by_status"].get(t["status"], 0) + 1
        if t["priority"]:
            summary["by_priority"][t["priority"]] = summary["by_priority"].get(t["priority"], 0) + 1

    return {
        "tasks": tasks,
        "summary": summary,
        "configured": bool(settings.clickup_api_token and settings.clickup_team_id),
    }


# ---------------------------------------------------------------------------
# DECI bidirectional sync
# ---------------------------------------------------------------------------

class DeciClickUpCreateIn(BaseModel):
    list_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[int] = None  # 1..4 per ClickUp API


class DeciClickUpLinkIn(BaseModel):
    task_id: str  # existing ClickUp task_id to link without creating


def _decision_response(decision: DeciDecision) -> dict[str, Any]:
    return {
        "id": decision.id,
        "title": decision.title,
        "status": decision.status,
        "clickup_task_id": decision.clickup_task_id,
        "clickup_status_cached": decision.clickup_status_cached,
        "clickup_url": decision.clickup_url,
        "clickup_last_synced_at": decision.clickup_last_synced_at.isoformat() if decision.clickup_last_synced_at else None,
    }


@router.post("/deci/{decision_id}/sync", status_code=201)
def deci_create_clickup_task(decision_id: str, body: DeciClickUpCreateIn, db: Session = Depends(db_session)) -> dict[str, Any]:
    if not (settings.clickup_api_token and settings.clickup_team_id):
        raise HTTPException(status_code=503, detail="ClickUp not configured")
    decision = db.get(DeciDecision, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    if decision.clickup_task_id:
        raise HTTPException(status_code=409, detail="Decision already linked to a ClickUp task — use /refresh or /unlink first")

    name = body.name or decision.title
    description_parts = [body.description or (decision.description or "")]
    description_parts.append("\n\n— Linked from Spider KPI DECI decision")
    description_parts.append(f"Decision ID: {decision.id}")
    due_dt: datetime | None = None
    if decision.due_date:
        due_dt = datetime.combine(decision.due_date, datetime.min.time()).replace(tzinfo=timezone.utc)

    task = create_task_in_list(
        list_id=body.list_id,
        name=name,
        description="\n".join([p for p in description_parts if p]),
        priority=body.priority,
        due_date=due_dt,
    )

    decision.clickup_task_id = str(task.get("id") or "")
    decision.clickup_url = task.get("url")
    status_obj = task.get("status") or {}
    if isinstance(status_obj, dict):
        decision.clickup_status_cached = status_obj.get("status")
    decision.clickup_last_synced_at = datetime.now(timezone.utc)

    db.add(DeciDecisionLog(
        decision_id=decision.id,
        decision_text=f"Created ClickUp task {decision.clickup_task_id} ({decision.clickup_url})",
        made_by="system:clickup_sync",
        notes=None,
    ))
    db.commit()
    return _decision_response(decision)


@router.post("/deci/{decision_id}/link")
def deci_link_existing_clickup_task(decision_id: str, body: DeciClickUpLinkIn, db: Session = Depends(db_session)) -> dict[str, Any]:
    if not (settings.clickup_api_token and settings.clickup_team_id):
        raise HTTPException(status_code=503, detail="ClickUp not configured")
    decision = db.get(DeciDecision, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    try:
        task = fetch_task(body.task_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not fetch ClickUp task {body.task_id}: {exc}")
    decision.clickup_task_id = str(task.get("id") or "")
    decision.clickup_url = task.get("url")
    status_obj = task.get("status") or {}
    if isinstance(status_obj, dict):
        decision.clickup_status_cached = status_obj.get("status")
    decision.clickup_last_synced_at = datetime.now(timezone.utc)
    db.add(DeciDecisionLog(
        decision_id=decision.id,
        decision_text=f"Linked existing ClickUp task {decision.clickup_task_id} ({decision.clickup_url})",
        made_by="system:clickup_sync",
        notes=None,
    ))
    db.commit()
    return _decision_response(decision)


@router.post("/deci/{decision_id}/refresh")
def deci_refresh_clickup_status(decision_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    if not (settings.clickup_api_token and settings.clickup_team_id):
        raise HTTPException(status_code=503, detail="ClickUp not configured")
    decision = db.get(DeciDecision, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    if not decision.clickup_task_id:
        raise HTTPException(status_code=400, detail="Decision not linked to a ClickUp task")

    task = fetch_task(decision.clickup_task_id)
    status_obj = task.get("status") or {}
    new_status = status_obj.get("status") if isinstance(status_obj, dict) else None
    previous = decision.clickup_status_cached
    decision.clickup_status_cached = new_status
    decision.clickup_url = task.get("url") or decision.clickup_url
    decision.clickup_last_synced_at = datetime.now(timezone.utc)

    if new_status and new_status != previous:
        db.add(DeciDecisionLog(
            decision_id=decision.id,
            decision_text=f"ClickUp status: {previous or '—'} → {new_status}",
            made_by="system:clickup_sync",
            notes=None,
        ))

    db.commit()
    return _decision_response(decision)


@router.post("/deci/{decision_id}/unlink")
def deci_unlink_clickup_task(decision_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    decision = db.get(DeciDecision, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    prior = decision.clickup_task_id
    decision.clickup_task_id = None
    decision.clickup_status_cached = None
    decision.clickup_url = None
    decision.clickup_last_synced_at = None
    if prior:
        db.add(DeciDecisionLog(
            decision_id=decision.id,
            decision_text=f"Unlinked ClickUp task {prior}",
            made_by="system:clickup_sync",
            notes=None,
        ))
    db.commit()
    return _decision_response(decision)


@router.post("/deci/{decision_id}/comment")
def deci_add_clickup_comment(decision_id: str, body: dict[str, str], db: Session = Depends(db_session)) -> dict[str, Any]:
    decision = db.get(DeciDecision, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    if not decision.clickup_task_id:
        raise HTTPException(status_code=400, detail="Decision not linked to a ClickUp task")
    text = (body.get("comment") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty comment")
    add_task_comment(decision.clickup_task_id, text)
    return {"ok": True, "task_id": decision.clickup_task_id}


@router.get("/deci/{decision_id}/comments")
def deci_list_clickup_comments(decision_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    decision = db.get(DeciDecision, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    if not decision.clickup_task_id:
        return {"comments": []}
    try:
        comments = fetch_task_comments(decision.clickup_task_id)
    except Exception:
        comments = []
    return {"comments": comments}


# ---------------------------------------------------------------------------
# Admin-triggered manual sync
# ---------------------------------------------------------------------------

@router.post("/sync-now")
def sync_now(full: bool = False, db: Session = Depends(db_session)) -> dict[str, Any]:
    return sync_clickup(db, full=full)
