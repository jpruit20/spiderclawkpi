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

import hashlib
import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_dashboard_session
from app.core.config import get_settings
from app.ingestion.connectors.clickup import (
    _append_event,
    _upsert_task,
    add_task_comment,
    create_task_in_list,
    delete_webhook as delete_clickup_webhook,
    fetch_task,
    fetch_task_comments,
    list_spaces,
    list_webhooks as list_clickup_webhooks,
    register_webhook as register_clickup_webhook,
    scan_tasks_for_issues,
    sync_clickup,
)
from app.models import (
    ClickUpTask,
    ClickUpTasksDaily,
    DeciDecision,
    DeciDecisionLog,
    SourceConfig,
)
from app.services.source_health import upsert_source_config


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/clickup",
    tags=["clickup"],
    dependencies=[Depends(require_dashboard_session)],
)

# Public webhook router — signature is the auth, no dashboard cookie required.
webhook_router = APIRouter(prefix="/api/webhooks/clickup", tags=["clickup_webhook"])

settings = get_settings()


# ---------------------------------------------------------------------------
# Webhook receiver
# ---------------------------------------------------------------------------

def _get_webhook_config(db: Session) -> dict[str, Any]:
    cfg = db.execute(select(SourceConfig).where(SourceConfig.source_name == "clickup_webhook")).scalars().first()
    return (cfg.config_json or {}) if cfg else {}


def _verify_clickup_signature(secret: str, body: bytes, signature: str) -> bool:
    if not secret or not signature:
        return False
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature)


def _handle_task_event(db: Session, event_type: str, task_id: str, webhook_payload: dict[str, Any]) -> None:
    if event_type == "taskDeleted":
        row = db.execute(select(ClickUpTask).where(ClickUpTask.task_id == task_id)).scalars().first()
        if row is not None:
            row.archived = True
            _append_event(db, task_id, "webhook.taskDeleted", datetime.now(timezone.utc),
                          webhook_payload, {"event": event_type})
        return
    try:
        task = fetch_task(task_id)
    except Exception:
        logger.warning("clickup webhook: failed to fetch task %s", task_id)
        return
    space = task.get("space") or {}
    list_meta = task.get("list") or {}
    folder = task.get("folder") or {}
    list_meta_with_folder = {
        **list_meta,
        "_folder_id": folder.get("id") if folder else None,
        "_folder_name": folder.get("name") if folder else None,
    }
    row, inserted, status_changed = _upsert_task(db, task, space, list_meta_with_folder)
    _append_event(db, row.task_id, f"webhook.{event_type}",
                  row.date_updated or datetime.now(timezone.utc),
                  webhook_payload, {
                      "status": row.status, "priority": row.priority,
                      "list_id": row.list_id, "space_id": row.space_id,
                      "inserted": inserted, "status_changed": status_changed,
                  })
    try:
        # Bounded scan — last hour — to pick up this task's new signal state.
        scan_tasks_for_issues(db, since=datetime.now(timezone.utc) - timedelta(hours=1))
        from app.compute.deci_autodraft import autodraft_from_signals
        autodraft_from_signals(db, since=datetime.now(timezone.utc) - timedelta(hours=1))
    except Exception:
        logger.exception("clickup webhook: scanner/autodraft failed (non-fatal)")


@webhook_router.post("/events")
async def clickup_events(request: Request, db: Session = Depends(db_session)) -> Response:
    body = await request.body()
    signature = request.headers.get("X-Signature", "")

    cfg = _get_webhook_config(db)
    secret = cfg.get("webhook_secret") or ""
    if not _verify_clickup_signature(secret, body, signature):
        raise HTTPException(status_code=401, detail="Invalid ClickUp signature")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    event_type = payload.get("event")
    task_id = payload.get("task_id")

    try:
        if task_id and event_type and event_type.startswith("task"):
            _handle_task_event(db, event_type, task_id, payload)
        else:
            logger.info("clickup webhook non-task event: %s", event_type)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("clickup webhook processing failed: %s", event_type)
    return Response(status_code=200)


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


# ---------------------------------------------------------------------------
# Webhook registration (one-time setup; idempotent)
# ---------------------------------------------------------------------------

class WebhookRegisterIn(BaseModel):
    endpoint_url: str  # public HTTPS URL of /api/webhooks/clickup/events


@router.get("/webhook/status")
def webhook_status(db: Session = Depends(db_session)) -> dict[str, Any]:
    cfg = _get_webhook_config(db)
    return {
        "registered": bool(cfg.get("webhook_id")),
        "webhook_id": cfg.get("webhook_id"),
        "endpoint_url": cfg.get("endpoint_url"),
        "configured_at": cfg.get("configured_at"),
        "events": cfg.get("events") or [],
    }


@router.post("/webhook/register")
def webhook_register(body: WebhookRegisterIn, db: Session = Depends(db_session)) -> dict[str, Any]:
    """Create a ClickUp webhook subscription pointing at our public endpoint.
    Stores the returned secret in ``source_configs['clickup_webhook']`` so the
    receiver can verify incoming payloads.

    Idempotent: if a webhook already exists on the ClickUp side at this URL,
    we leave it and only re-store the secret from the fresh call.
    """
    if not (settings.clickup_api_token and settings.clickup_team_id):
        raise HTTPException(status_code=503, detail="ClickUp not configured")

    existing_cfg = _get_webhook_config(db)
    existing_id = existing_cfg.get("webhook_id")

    # If ClickUp already has a webhook at this URL (from a prior register),
    # surface that rather than duplicating.
    try:
        hooks = list_clickup_webhooks()
    except Exception:
        hooks = []
    duplicate = next((h for h in hooks if h.get("endpoint") == body.endpoint_url), None)

    if duplicate and existing_id == duplicate.get("id"):
        return {
            "ok": True,
            "status": "already_registered",
            "webhook_id": existing_id,
            "endpoint_url": body.endpoint_url,
            "events": existing_cfg.get("events") or [],
        }

    # Create fresh webhook (ClickUp returns a NEW secret each create).
    resp = register_clickup_webhook(body.endpoint_url)
    webhook = resp.get("webhook") or {}
    wid = str(webhook.get("id") or "")
    secret = webhook.get("secret")
    if not wid or not secret:
        raise HTTPException(status_code=502, detail=f"ClickUp webhook create returned unexpected shape: {resp}")

    upsert_source_config(
        db, "clickup_webhook",
        configured=True,
        sync_mode="events",
        config_json={
            "webhook_id": wid,
            "webhook_secret": secret,
            "endpoint_url": body.endpoint_url,
            "events": webhook.get("events") or [],
            "configured_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    db.commit()

    # Best-effort cleanup: if we had a stale webhook_id in our config and it
    # isn't the one we just created, try to remove it on the ClickUp side.
    if existing_id and existing_id != wid:
        try:
            delete_clickup_webhook(existing_id)
        except Exception:
            logger.exception("failed to delete stale ClickUp webhook %s", existing_id)

    return {
        "ok": True,
        "status": "registered",
        "webhook_id": wid,
        "endpoint_url": body.endpoint_url,
        "events": webhook.get("events") or [],
    }


@router.post("/webhook/unregister")
def webhook_unregister(db: Session = Depends(db_session)) -> dict[str, Any]:
    cfg = _get_webhook_config(db)
    wid = cfg.get("webhook_id")
    if not wid:
        return {"ok": True, "status": "not_registered"}
    ok = False
    try:
        ok = delete_clickup_webhook(wid)
    except Exception:
        logger.exception("delete webhook failed")
    upsert_source_config(
        db, "clickup_webhook",
        configured=False,
        sync_mode="events",
        config_json={},
    )
    db.commit()
    return {"ok": True, "status": "unregistered" if ok else "delete_failed", "webhook_id": wid}


# ---------------------------------------------------------------------------
# Velocity — throughput + cycle time per space
# ---------------------------------------------------------------------------

@router.get("/velocity")
def velocity(space_id: Optional[str] = None, days: int = 30, db: Session = Depends(db_session)) -> dict[str, Any]:
    """Team throughput + cycle time derived from clickup_tasks_daily + clickup_tasks.

    - ``throughput``: closed-per-day over the window, sparkline-shaped
    - ``week_over_week``: this-7-days vs prior-7-days delta for closed count
    - ``cycle_time_median_days``: p50 of (date_done - date_created) for
       tasks closed in the window
    - ``top_closers``: top 5 usernames who closed the most in the window
    """
    days = max(1, min(days, 180))
    today = datetime.now(timezone.utc).date()
    start_date = today - timedelta(days=days - 1)

    daily_stmt = select(ClickUpTasksDaily).where(
        ClickUpTasksDaily.business_date >= start_date,
        ClickUpTasksDaily.business_date <= today,
    )
    if space_id:
        daily_stmt = daily_stmt.where(ClickUpTasksDaily.space_id == space_id)
    daily_stmt = daily_stmt.order_by(ClickUpTasksDaily.business_date)
    daily_rows = db.execute(daily_stmt).scalars().all()

    # Daily throughput — sum across spaces if no filter
    per_day: dict[str, dict[str, int]] = {}
    for r in daily_rows:
        k = r.business_date.isoformat()
        bucket = per_day.setdefault(k, {"created": 0, "completed": 0, "open_pit": 0, "overdue_pit": 0})
        bucket["created"] += int(r.tasks_created or 0)
        bucket["completed"] += int(r.tasks_completed or 0)
        bucket["open_pit"] = int(r.tasks_open or 0)  # last-write-wins is fine for point-in-time fields when unfiltered
        bucket["overdue_pit"] = int(r.tasks_overdue or 0)
    throughput = [
        {"date": d, **per_day[d]}
        for d in sorted(per_day.keys())
    ]

    # Week over week — closed count in last 7 days vs prior 7
    cutoff_this = today - timedelta(days=7)
    cutoff_prev = today - timedelta(days=14)
    closed_last_7 = sum(b["completed"] for d, b in per_day.items() if d >= cutoff_this.isoformat())
    closed_prior_7 = sum(b["completed"] for d, b in per_day.items() if cutoff_prev.isoformat() <= d < cutoff_this.isoformat())
    wow_delta = closed_last_7 - closed_prior_7
    wow_pct = (wow_delta / closed_prior_7 * 100.0) if closed_prior_7 else None

    # Cycle time — tasks that completed during the window
    win_start = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    tasks_stmt = select(ClickUpTask).where(
        ClickUpTask.date_done.isnot(None),
        ClickUpTask.date_done >= win_start,
        ClickUpTask.date_created.isnot(None),
    )
    if space_id:
        tasks_stmt = tasks_stmt.where(ClickUpTask.space_id == space_id)
    tasks = db.execute(tasks_stmt).scalars().all()
    durations = []
    for t in tasks:
        try:
            d = (t.date_done - t.date_created).total_seconds()
            if d > 0:
                durations.append(d)
        except Exception:
            pass
    median_sec = None
    p90_sec = None
    if durations:
        s = sorted(durations)
        median_sec = s[len(s) // 2]
        p90_sec = s[int(len(s) * 0.9) - 1] if len(s) >= 10 else None

    # Top closers — by assignee username
    closer_counter: dict[str, int] = {}
    for t in tasks:
        for a in (t.assignees_json or []):
            name = (a or {}).get("username") or (a or {}).get("email")
            if name:
                closer_counter[name] = closer_counter.get(name, 0) + 1
    top_closers = sorted(closer_counter.items(), key=lambda kv: kv[1], reverse=True)[:5]

    # Current open/overdue — computed directly from clickup_tasks for accuracy
    now_dt = datetime.now(timezone.utc)
    open_stmt = select(func.count(ClickUpTask.id)).where(
        or_(ClickUpTask.status_type.is_(None), ClickUpTask.status_type != "closed"),
        ClickUpTask.archived == False,  # noqa: E712
    )
    overdue_stmt = open_stmt.where(
        ClickUpTask.due_date.isnot(None),
        ClickUpTask.due_date < now_dt,
    )
    if space_id:
        open_stmt = open_stmt.where(ClickUpTask.space_id == space_id)
        overdue_stmt = overdue_stmt.where(ClickUpTask.space_id == space_id)
    open_count = int(db.execute(open_stmt).scalar() or 0)
    overdue_count = int(db.execute(overdue_stmt).scalar() or 0)

    return {
        "window": {"start": start_date.isoformat(), "end": today.isoformat(), "days": days},
        "space_id": space_id,
        "throughput": throughput,
        "totals": {
            "closed_last_7": closed_last_7,
            "closed_prior_7": closed_prior_7,
            "wow_delta": wow_delta,
            "wow_pct": wow_pct,
            "open_now": open_count,
            "overdue_now": overdue_count,
        },
        "cycle_time": {
            "median_seconds": median_sec,
            "median_days": (median_sec / 86400.0) if median_sec else None,
            "p90_seconds": p90_sec,
            "p90_days": (p90_sec / 86400.0) if p90_sec else None,
            "sample_size": len(durations),
        },
        "top_closers": [{"user": u, "completed": c} for u, c in top_closers],
    }
