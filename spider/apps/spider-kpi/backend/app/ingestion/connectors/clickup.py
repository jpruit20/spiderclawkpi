"""ClickUp connector.

Polls the ClickUp v2 API, upserts tasks into ``clickup_tasks``, appends
status-change snapshots to ``clickup_task_events``, and rebuilds the
``clickup_tasks_daily`` rollup.

Also exposes ``create_clickup_task`` / ``fetch_task`` / ``update_task_status``
helpers used by the DECI integration to bidirectionally mirror a decision
against a real ClickUp task.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    ClickUpTask,
    ClickUpTaskEvent,
    ClickUpTasksDaily,
    IssueSignal,
)
from app.services.source_health import finish_sync_run, start_sync_run, upsert_source_config

import re as _re_for_scanner


settings = get_settings()
logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(logging.Formatter('%(levelname)s:%(name)s:%(message)s'))
    logger.addHandler(stream_handler)

TIMEOUT_SECONDS = 30
BUSINESS_TZ = ZoneInfo("America/New_York")
SOURCE_NAME = "clickup"


def _configured() -> bool:
    return bool(settings.clickup_api_token and settings.clickup_team_id)


def _headers() -> dict[str, str]:
    return {
        "Authorization": settings.clickup_api_token or "",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _parse_dt(value: Any) -> Optional[datetime]:
    """ClickUp returns unix-ms timestamps as strings. Return None on any problem."""
    if value in (None, "", 0, "0"):
        return None
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _business_date(value: datetime | None) -> date | None:
    if value is None:
        return None
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(BUSINESS_TZ).date()


def _status_fields(task: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    status = task.get("status") or {}
    if isinstance(status, dict):
        return status.get("status"), status.get("type")
    if isinstance(status, str):
        return status, None
    return None, None


def _priority_name(task: dict[str, Any]) -> Optional[str]:
    pr = task.get("priority")
    if isinstance(pr, dict):
        return pr.get("priority") or pr.get("name")
    if isinstance(pr, (str, int)):
        return str(pr)
    return None


def _assignee_summary(task: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for a in task.get("assignees") or []:
        if not isinstance(a, dict):
            continue
        out.append({
            "id": str(a.get("id") or ""),
            "username": a.get("username"),
            "email": a.get("email"),
        })
    return out


def _tag_names(task: dict[str, Any]) -> list[str]:
    out = []
    for t in task.get("tags") or []:
        if isinstance(t, dict):
            name = t.get("name")
            if name:
                out.append(str(name))
        elif isinstance(t, str):
            out.append(t)
    return out


# ---------------------------------------------------------------------------
# Workspace discovery
# ---------------------------------------------------------------------------

def list_spaces(team_id: str | None = None) -> list[dict[str, Any]]:
    team_id = team_id or settings.clickup_team_id
    if not team_id:
        return []
    r = requests.get(
        f"{settings.clickup_base_url}/team/{team_id}/space?archived=false",
        headers=_headers(),
        timeout=TIMEOUT_SECONDS,
    )
    r.raise_for_status()
    return r.json().get("spaces", [])


def list_lists_in_space(space_id: str) -> list[dict[str, Any]]:
    """All lists reachable inside a space (folderless + folder-wrapped)."""
    out: list[dict[str, Any]] = []

    # Folderless lists.
    r = requests.get(
        f"{settings.clickup_base_url}/space/{space_id}/list?archived=false",
        headers=_headers(),
        timeout=TIMEOUT_SECONDS,
    )
    r.raise_for_status()
    for l in r.json().get("lists", []):
        out.append({**l, "_folder_id": None, "_folder_name": None})

    # Folders → lists.
    r = requests.get(
        f"{settings.clickup_base_url}/space/{space_id}/folder?archived=false",
        headers=_headers(),
        timeout=TIMEOUT_SECONDS,
    )
    r.raise_for_status()
    for f in r.json().get("folders", []):
        for l in f.get("lists", []) or []:
            out.append({**l, "_folder_id": f.get("id"), "_folder_name": f.get("name")})

    return out


# ---------------------------------------------------------------------------
# Task ingestion
# ---------------------------------------------------------------------------

def _iter_tasks_in_list(list_id: str, date_updated_gt_ms: int | None = None) -> Iterable[dict[str, Any]]:
    """Paginate ClickUp's /list/{id}/task endpoint (100/page)."""
    page = 0
    while True:
        params: dict[str, Any] = {
            "archived": "false",
            "include_closed": "true",
            "subtasks": "true",
            "page": page,
        }
        if date_updated_gt_ms:
            params["date_updated_gt"] = date_updated_gt_ms
        r = requests.get(
            f"{settings.clickup_base_url}/list/{list_id}/task",
            headers=_headers(),
            params=params,
            timeout=TIMEOUT_SECONDS,
        )
        if r.status_code == 429:
            # ClickUp rate-limit — back off once and retry.
            retry_after = float(r.headers.get("Retry-After") or 2)
            logger.warning("clickup rate-limited, sleeping %.1fs", retry_after)
            time.sleep(retry_after)
            continue
        r.raise_for_status()
        batch = r.json().get("tasks", []) or []
        if not batch:
            return
        for t in batch:
            yield t
        if len(batch) < 100:
            return
        page += 1


def _upsert_task(
    db: Session,
    task: dict[str, Any],
    space_meta: dict[str, Any],
    list_meta: dict[str, Any],
) -> tuple[ClickUpTask, bool, bool]:
    """Insert or update a task row. Returns (row, inserted, status_changed)."""
    task_id = str(task.get("id") or "").strip()
    if not task_id:
        raise ValueError("task missing id")

    status_name, status_type = _status_fields(task)
    priority = _priority_name(task)
    date_updated = _parse_dt(task.get("date_updated"))

    row = db.execute(
        select(ClickUpTask).where(ClickUpTask.task_id == task_id)
    ).scalars().first()
    inserted = False
    status_changed = False
    if row is None:
        row = ClickUpTask(task_id=task_id)
        db.add(row)
        inserted = True
    else:
        status_changed = row.status != status_name

    row.custom_id = str(task.get("custom_id")) if task.get("custom_id") else None
    row.name = str(task.get("name") or "")[:500] or None
    row.description = task.get("text_content") or task.get("description") or None
    row.status = status_name
    row.status_type = status_type
    row.priority = priority
    row.team_id = str(task.get("team_id") or "") or None
    row.space_id = str(space_meta.get("id") or "") or None
    row.space_name = space_meta.get("name")
    row.folder_id = list_meta.get("_folder_id")
    row.folder_name = list_meta.get("_folder_name")
    row.list_id = str(list_meta.get("id") or "") or None
    row.list_name = list_meta.get("name")
    parent = task.get("parent")
    row.parent_task_id = str(parent) if parent else None
    creator = task.get("creator") or {}
    row.creator_id = str(creator.get("id")) if creator.get("id") is not None else None
    row.creator_username = creator.get("username")
    row.assignees_json = _assignee_summary(task)
    row.tags_json = _tag_names(task)
    row.custom_fields_json = task.get("custom_fields") or []
    row.url = task.get("url")
    points = task.get("points")
    row.points = float(points) if isinstance(points, (int, float)) else None
    te = task.get("time_estimate")
    row.time_estimate_ms = int(te) if isinstance(te, (int, float)) else None
    row.date_created = _parse_dt(task.get("date_created"))
    row.date_updated = date_updated
    row.date_closed = _parse_dt(task.get("date_closed"))
    row.date_done = _parse_dt(task.get("date_done"))
    row.start_date = _parse_dt(task.get("start_date"))
    row.due_date = _parse_dt(task.get("due_date"))
    row.archived = bool(task.get("archived"))
    row.raw_payload = task
    return row, inserted, status_changed


def _append_event(db: Session, task_id: str, event_type: str, timestamp: datetime | None, payload: dict[str, Any], normalized: dict[str, Any]) -> None:
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    exists = db.execute(
        select(ClickUpTaskEvent).where(
            ClickUpTaskEvent.task_id == task_id,
            ClickUpTaskEvent.event_type == event_type,
            ClickUpTaskEvent.event_timestamp == timestamp,
        ).limit(1)
    ).scalars().first()
    if exists is not None:
        return
    db.add(ClickUpTaskEvent(
        task_id=task_id,
        event_type=event_type,
        event_timestamp=timestamp,
        raw_payload=payload,
        normalized_payload=normalized,
    ))


# ---------------------------------------------------------------------------
# Daily rollup
# ---------------------------------------------------------------------------

def rebuild_clickup_daily(db: Session, start_date: date, end_date: date) -> int:
    """Full rebuild of ``clickup_tasks_daily`` for [start_date, end_date].

    Open/overdue counts are point-in-time "as of end_date" snapshots applied to
    every day in the range — simple and sufficient for a rolling dashboard.
    Created/completed counts are per-day based on date_created/date_done.
    """
    if start_date > end_date:
        return 0

    tasks = db.execute(select(ClickUpTask)).scalars().all()
    today = datetime.now(BUSINESS_TZ).date()

    per_day: dict[tuple[date, str | None], dict[str, Any]] = defaultdict(lambda: {
        "space_name": None,
        "tasks_created": 0, "tasks_completed": 0, "tasks_open": 0, "tasks_closed": 0,
        "tasks_overdue": 0,
        "status_breakdown": defaultdict(int),
        "priority_breakdown": defaultdict(int),
        "assignee_breakdown": defaultdict(int),
    })

    # Per-day created/completed (event-ish)
    for t in tasks:
        space_id = t.space_id
        created_bd = _business_date(t.date_created)
        done_bd = _business_date(t.date_done or t.date_closed)
        if created_bd and start_date <= created_bd <= end_date:
            per_day[(created_bd, space_id)]["space_name"] = t.space_name
            per_day[(created_bd, space_id)]["tasks_created"] += 1
        if done_bd and start_date <= done_bd <= end_date:
            per_day[(done_bd, space_id)]["space_name"] = t.space_name
            per_day[(done_bd, space_id)]["tasks_completed"] += 1

    # Point-in-time snapshots applied to every day in window.
    snapshot_by_space: dict[str | None, dict[str, Any]] = defaultdict(lambda: {
        "space_name": None,
        "open": 0, "closed": 0, "overdue": 0,
        "status_breakdown": defaultdict(int),
        "priority_breakdown": defaultdict(int),
        "assignee_breakdown": defaultdict(int),
    })
    for t in tasks:
        space_id = t.space_id
        snap = snapshot_by_space[space_id]
        snap["space_name"] = t.space_name
        is_open = (t.status_type or "").lower() != "closed" and not t.archived
        if is_open:
            snap["open"] += 1
            if t.due_date and t.due_date.astimezone(BUSINESS_TZ).date() < today:
                snap["overdue"] += 1
        else:
            snap["closed"] += 1
        if t.status:
            snap["status_breakdown"][t.status] += 1
        if t.priority:
            snap["priority_breakdown"][t.priority] += 1
        for a in (t.assignees_json or []):
            name = (a or {}).get("username") or (a or {}).get("email") or str((a or {}).get("id", ""))
            if name:
                snap["assignee_breakdown"][name] += 1

    # Wipe the target window and rewrite.
    db.execute(delete(ClickUpTasksDaily).where(
        ClickUpTasksDaily.business_date >= start_date,
        ClickUpTasksDaily.business_date <= end_date,
    ))
    db.flush()

    cur = start_date
    rows_written = 0
    all_space_keys = set(snapshot_by_space.keys())
    while cur <= end_date:
        for space_id in all_space_keys:
            snap = snapshot_by_space[space_id]
            day_rec = per_day.get((cur, space_id), {})
            row = ClickUpTasksDaily(
                business_date=cur,
                space_id=space_id,
                space_name=snap["space_name"] or day_rec.get("space_name"),
                tasks_open=snap["open"],
                tasks_closed=snap["closed"],
                tasks_overdue=snap["overdue"],
                tasks_created=day_rec.get("tasks_created", 0),
                tasks_completed=day_rec.get("tasks_completed", 0),
                status_breakdown=dict(snap["status_breakdown"]),
                priority_breakdown=dict(snap["priority_breakdown"]),
                assignee_breakdown=dict(snap["assignee_breakdown"]),
            )
            db.add(row)
            rows_written += 1
        cur += timedelta(days=1)

    return rows_written


# ---------------------------------------------------------------------------
# Public sync entry point
# ---------------------------------------------------------------------------

def sync_clickup(db: Session, full: bool = False) -> dict[str, Any]:
    """Walk every list in every space, upsert tasks, rebuild rollup.

    ``full=False`` uses a date_updated_gt filter to pull only recently-changed
    tasks (honors ``CLICKUP_TASK_LOOKBACK_DAYS``). ``full=True`` pulls
    everything (used on first sync or a manual re-bootstrap).
    """
    started = time.monotonic()
    upsert_source_config(
        db, SOURCE_NAME,
        configured=_configured(),
        sync_mode="poll",
        config_json={"team_id": settings.clickup_team_id, "base_url": settings.clickup_base_url},
    )
    db.commit()
    if not _configured():
        return {"ok": False, "message": "ClickUp not configured", "records_processed": 0}

    run = start_sync_run(db, SOURCE_NAME, "poll_recent" if not full else "poll_full", {
        "team_id": settings.clickup_team_id,
        "lookback_days": settings.clickup_task_lookback_days,
        "full": full,
    })
    db.commit()

    stats = {
        "spaces_scanned": 0,
        "lists_scanned": 0,
        "tasks_fetched": 0,
        "tasks_inserted": 0,
        "tasks_updated": 0,
        "status_changes": 0,
    }

    try:
        spaces = list_spaces()
        stats["spaces_scanned"] = len(spaces)

        since_ms: int | None = None
        if not full:
            since_ms = int((datetime.now(timezone.utc) - timedelta(days=settings.clickup_task_lookback_days)).timestamp() * 1000)

        affected_dates: set[date] = set()

        for space in spaces:
            lists = list_lists_in_space(space["id"])
            stats["lists_scanned"] += len(lists)
            for list_meta in lists:
                list_id = str(list_meta.get("id") or "")
                if not list_id:
                    continue
                for task in _iter_tasks_in_list(list_id, date_updated_gt_ms=since_ms):
                    stats["tasks_fetched"] += 1
                    row, inserted, status_changed = _upsert_task(db, task, space, list_meta)
                    if inserted:
                        stats["tasks_inserted"] += 1
                    else:
                        stats["tasks_updated"] += 1

                    # Append a snapshot event (one per date_updated tick).
                    _append_event(
                        db, row.task_id,
                        event_type="poll.task_snapshot",
                        timestamp=row.date_updated or datetime.now(timezone.utc),
                        payload=task,
                        normalized={
                            "status": row.status, "priority": row.priority,
                            "list_id": row.list_id, "space_id": row.space_id,
                        },
                    )
                    if status_changed and row.status:
                        stats["status_changes"] += 1
                        _append_event(
                            db, row.task_id,
                            event_type="status_change",
                            timestamp=row.date_updated or datetime.now(timezone.utc),
                            payload={"task_id": row.task_id, "to": row.status},
                            normalized={"status": row.status},
                        )
                    bd = _business_date(row.date_updated) or _business_date(row.date_created)
                    if bd:
                        affected_dates.add(bd)

        # Rebuild a slightly wider daily window so yesterday's snapshot stays fresh.
        today = datetime.now(BUSINESS_TZ).date()
        window_start = min(affected_dates) if affected_dates else today - timedelta(days=settings.clickup_task_lookback_days)
        window_end = today
        rollup_rows = rebuild_clickup_daily(db, window_start, window_end)
        stats["rollup_rows_written"] = rollup_rows

        # Scan tasks for issue-shaped language and urgent priority flags.
        issues = scan_tasks_for_issues(
            db,
            since=datetime.now(timezone.utc) - timedelta(days=settings.clickup_task_lookback_days),
        )
        stats["issue_signals_inserted"] = issues
        db.commit()

        # Feed the DECI auto-draft engine.
        try:
            from app.compute.deci_autodraft import autodraft_from_signals
            stats["autodraft"] = autodraft_from_signals(
                db,
                since=datetime.now(timezone.utc) - timedelta(days=settings.clickup_task_lookback_days),
            )
            db.commit()
        except Exception:
            logger.exception("clickup autodraft failed (non-fatal)")
            db.rollback()

        duration_ms = int((time.monotonic() - started) * 1000)
        run.metadata_json = {**(run.metadata_json or {}), **stats, "duration_ms": duration_ms}
        finish_sync_run(db, run, status="success", records_processed=stats["tasks_fetched"])
        db.commit()
        logger.info("clickup sync complete: %s", stats)
        return {"ok": True, **stats, "duration_ms": duration_ms}
    except Exception as exc:
        db.rollback()
        run = db.merge(run)
        duration_ms = int((time.monotonic() - started) * 1000)
        run.metadata_json = {**(run.metadata_json or {}), **stats, "duration_ms": duration_ms}
        finish_sync_run(db, run, status="failed", error_message=str(exc))
        db.commit()
        logger.exception("clickup sync failed")
        return {"ok": False, "message": str(exc), **stats, "duration_ms": duration_ms}


# ---------------------------------------------------------------------------
# DECI integration helpers (bidirectional sync for a single task)
# ---------------------------------------------------------------------------

def create_task_in_list(list_id: str, name: str, description: str | None = None,
                         priority: int | None = None, due_date: datetime | None = None) -> dict[str, Any]:
    """Create a single ClickUp task. Used when a DECI decision opts into sync."""
    if not _configured():
        raise RuntimeError("ClickUp not configured")
    payload: dict[str, Any] = {"name": name}
    if description:
        payload["description"] = description
    if priority is not None:
        payload["priority"] = priority  # 1=urgent, 2=high, 3=normal, 4=low
    if due_date:
        payload["due_date"] = int(due_date.timestamp() * 1000)
    r = requests.post(
        f"{settings.clickup_base_url}/list/{list_id}/task",
        headers=_headers(),
        json=payload,
        timeout=TIMEOUT_SECONDS,
    )
    r.raise_for_status()
    return r.json()


def fetch_task(task_id: str) -> dict[str, Any]:
    if not _configured():
        raise RuntimeError("ClickUp not configured")
    r = requests.get(
        f"{settings.clickup_base_url}/task/{task_id}",
        headers=_headers(),
        timeout=TIMEOUT_SECONDS,
    )
    r.raise_for_status()
    return r.json()


def fetch_task_comments(task_id: str) -> list[dict[str, Any]]:
    if not _configured():
        return []
    r = requests.get(
        f"{settings.clickup_base_url}/task/{task_id}/comment",
        headers=_headers(),
        timeout=TIMEOUT_SECONDS,
    )
    if r.status_code >= 400:
        return []
    return r.json().get("comments", []) or []


def scan_tasks_for_issues(db: Session, since: datetime | None = None) -> int:
    """Scan ClickUp tasks updated since ``since`` for issue-shaped language.

    Writes matching rows into ``issue_signals`` with ``source='clickup'``
    using the same pattern set as the Slack scanner (so both streams feed
    Issue Radar + the DECI auto-draft engine under a unified vocabulary).
    Idempotent — dedups on (source, signal_type, metadata.task_id).
    """
    # Reuse the same pattern list as Slack to keep vocabulary consistent.
    from app.ingestion.connectors.slack import DEFAULT_ISSUE_PATTERNS
    compiled = [(p["name"], p["severity"], _re_for_scanner.compile(p["regex"], _re_for_scanner.IGNORECASE))
                for p in DEFAULT_ISSUE_PATTERNS]

    if since is None:
        since = datetime.now(timezone.utc) - timedelta(days=2)

    tasks = db.execute(
        select(ClickUpTask).where(ClickUpTask.date_updated >= since)
    ).scalars().all()

    inserted = 0
    for t in tasks:
        # Combined text surface: task name + description. Comments aren't
        # polled per-task today (cheaper to treat them as a later tick).
        text = " ".join(filter(None, [t.name or "", t.description or ""]))
        if not text.strip():
            continue
        for name, severity, rx in compiled:
            if not rx.search(text):
                continue
            existing = db.execute(select(IssueSignal).where(
                IssueSignal.source == "clickup",
                IssueSignal.signal_type == f"clickup.{name}",
                IssueSignal.metadata_json["task_id"].astext == t.task_id,
            )).scalars().first()
            if existing is not None:
                continue
            bd = (t.date_updated or t.date_created)
            bd = bd.astimezone(timezone.utc).date() if bd else None
            db.add(IssueSignal(
                business_date=bd,
                signal_type=f"clickup.{name}",
                severity=severity,
                confidence=0.6,
                source="clickup",
                title=(t.name or "")[:120] or f"ClickUp {name}",
                summary=(text or "")[:500],
                metadata_json={
                    "task_id": t.task_id,
                    "custom_id": t.custom_id,
                    "url": t.url,
                    "list_id": t.list_id,
                    "list_name": t.list_name,
                    "space_id": t.space_id,
                    "space_name": t.space_name,
                    "status": t.status,
                    "priority": t.priority,
                    "pattern": name,
                    "assignees": t.assignees_json,
                },
            ))
            inserted += 1
            break  # one signal per task is enough

    # Also flag any task whose ClickUp priority is 'urgent' — first-class
    # signal that bypasses keyword match (Joseph/team already said it's hot).
    urgent_tasks = db.execute(
        select(ClickUpTask).where(
            ClickUpTask.date_updated >= since,
            ClickUpTask.priority == "urgent",
        )
    ).scalars().all()
    for t in urgent_tasks:
        existing = db.execute(select(IssueSignal).where(
            IssueSignal.source == "clickup",
            IssueSignal.signal_type == "clickup.urgent_priority",
            IssueSignal.metadata_json["task_id"].astext == t.task_id,
        )).scalars().first()
        if existing is not None:
            continue
        bd = (t.date_updated or t.date_created)
        bd = bd.astimezone(timezone.utc).date() if bd else None
        db.add(IssueSignal(
            business_date=bd,
            signal_type="clickup.urgent_priority",
            severity="critical",
            confidence=0.8,
            source="clickup",
            title=f"Urgent ClickUp task: {(t.name or '')[:100]}",
            summary=((t.description or t.name or "") or "")[:500],
            metadata_json={
                "task_id": t.task_id,
                "url": t.url,
                "list_id": t.list_id,
                "list_name": t.list_name,
                "space_id": t.space_id,
                "space_name": t.space_name,
                "priority": t.priority,
                "status": t.status,
                "pattern": "urgent_priority",
                "assignees": t.assignees_json,
            },
        ))
        inserted += 1

    db.flush()
    return inserted


def add_task_comment(task_id: str, comment: str) -> dict[str, Any]:
    if not _configured():
        raise RuntimeError("ClickUp not configured")
    r = requests.post(
        f"{settings.clickup_base_url}/task/{task_id}/comment",
        headers=_headers(),
        json={"comment_text": comment},
        timeout=TIMEOUT_SECONDS,
    )
    r.raise_for_status()
    return r.json()
