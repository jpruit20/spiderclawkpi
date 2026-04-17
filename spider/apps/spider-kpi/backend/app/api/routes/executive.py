"""Executive — single aggregated "morning brief" endpoint.

``GET /api/executive/morning`` pulls the top N items across every integrated
source so Joseph has one screen to open at 8am and know what needs attention.
Nothing new is computed — it's pure synthesis of already-materialized data.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_dashboard_session
from app.models import (
    ClickUpTask,
    DeciDecision,
    IssueSignal,
    KPIDaily,
    SlackMessage,
    SlackUser,
    TelemetryHistoryDaily,
)


logger = logging.getLogger(__name__)
BUSINESS_TZ = ZoneInfo("America/New_York")

router = APIRouter(
    prefix="/api/executive",
    tags=["executive"],
    dependencies=[Depends(require_dashboard_session)],
)


def _safe_list(items: Any) -> list:
    return list(items) if items else []


@router.get("/morning")
def morning_brief(db: Session = Depends(db_session)) -> dict[str, Any]:
    """The coffee-in-hand aggregated view. Everything material, nothing else."""
    now = datetime.now(timezone.utc)
    today_local = datetime.now(BUSINESS_TZ).date()
    since_24h = now - timedelta(hours=24)

    # --- DECI drafts awaiting review --------------------------------------
    drafts_rows = db.execute(
        select(DeciDecision)
        .where(DeciDecision.status == "draft")
        .order_by(DeciDecision.auto_drafted_at.desc().nulls_last(), DeciDecision.created_at.desc())
        .limit(5)
    ).scalars().all()
    total_drafts = int(db.execute(
        select(func.count(DeciDecision.id)).where(DeciDecision.status == "draft")
    ).scalar() or 0)

    drafts_payload = [
        {
            "id": d.id,
            "title": d.title,
            "priority": d.priority,
            "department": d.department,
            "origin_signal_type": d.origin_signal_type,
            "auto_drafted_at": d.auto_drafted_at.isoformat() if d.auto_drafted_at else None,
        }
        for d in drafts_rows
    ]

    # --- Critical IssueSignals in last 24h --------------------------------
    critical_rows = db.execute(
        select(IssueSignal)
        .where(IssueSignal.severity == "critical", IssueSignal.created_at >= since_24h)
        .order_by(IssueSignal.created_at.desc())
        .limit(6)
    ).scalars().all()

    critical_payload = []
    for s in critical_rows:
        meta = s.metadata_json or {}
        ai = meta.get("ai") if isinstance(meta, dict) else None
        title = (ai or {}).get("title") if isinstance(ai, dict) else None
        critical_payload.append({
            "id": s.id,
            "signal_type": s.signal_type,
            "source": s.source,
            "title": title or s.title,
            "summary": (ai or {}).get("summary") if isinstance(ai, dict) else s.summary,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "metadata": {
                "channel_id": meta.get("channel_id"),
                "task_id": meta.get("task_id"),
                "url": meta.get("url"),
            },
        })

    # --- Stale/overdue urgent + high priority ClickUp tasks ---------------
    stale_rows = db.execute(
        select(ClickUpTask)
        .where(
            ClickUpTask.archived == False,  # noqa: E712
            or_(ClickUpTask.status_type.is_(None), ClickUpTask.status_type != "closed"),
            ClickUpTask.due_date.isnot(None),
            ClickUpTask.due_date < now,
            ClickUpTask.priority.in_(["urgent", "high"]),
        )
        .order_by(ClickUpTask.due_date)
        .limit(6)
    ).scalars().all()
    stale_payload = [
        {
            "task_id": t.task_id,
            "name": t.name,
            "url": t.url,
            "priority": t.priority,
            "space_name": t.space_name,
            "list_name": t.list_name,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "days_overdue": int((now - t.due_date).total_seconds() // 86400) if t.due_date else 0,
            "assignees": [((a or {}).get("username") or (a or {}).get("email")) for a in (t.assignees_json or [])],
        }
        for t in stale_rows
    ]

    # --- Revenue trailing 7 days (from kpi_daily) -------------------------
    rev_cutoff_7 = today_local - timedelta(days=7)
    rev_cutoff_14 = today_local - timedelta(days=14)
    revenue_rows = db.execute(
        select(KPIDaily.business_date, KPIDaily.revenue)
        .where(KPIDaily.business_date >= rev_cutoff_14)
        .order_by(KPIDaily.business_date)
    ).all()
    rev_last_7 = sum(float(r.revenue or 0) for r in revenue_rows if r.business_date >= rev_cutoff_7)
    rev_prior_7 = sum(float(r.revenue or 0) for r in revenue_rows if rev_cutoff_14 <= r.business_date < rev_cutoff_7)
    revenue_payload = {
        "trailing_7": rev_last_7,
        "prior_7": rev_prior_7,
        "wow_delta": rev_last_7 - rev_prior_7,
        "wow_pct": ((rev_last_7 - rev_prior_7) / rev_prior_7 * 100.0) if rev_prior_7 else None,
        "sparkline": [
            {"date": r.business_date.isoformat(), "revenue": float(r.revenue or 0)}
            for r in revenue_rows[-14:]
        ],
    }

    # --- Telemetry headline (latest row from telemetry_history_daily) ----
    tel_row = db.execute(
        select(TelemetryHistoryDaily)
        .order_by(TelemetryHistoryDaily.business_date.desc())
        .limit(1)
    ).scalars().first()
    telemetry_payload = None
    if tel_row:
        error_rate = (tel_row.error_events / tel_row.total_events) if (tel_row.total_events or 0) > 0 else None
        cook_success = None
        if tel_row.session_count and tel_row.session_count > 0:
            cook_success = (tel_row.successful_sessions or 0) / tel_row.session_count
        telemetry_payload = {
            "business_date": tel_row.business_date.isoformat(),
            "active_devices": tel_row.active_devices,
            "engaged_devices": tel_row.engaged_devices,
            "total_events": tel_row.total_events,
            "error_events": tel_row.error_events,
            "error_rate": error_rate,
            "cook_success_rate": cook_success,
            "session_count": tel_row.session_count,
        }

    # --- ClickUp velocity headline (closed in last 7d vs prior 7d) -------
    close_cutoff_7 = now - timedelta(days=7)
    close_cutoff_14 = now - timedelta(days=14)
    closed_last_7 = int(db.execute(
        select(func.count(ClickUpTask.id))
        .where(ClickUpTask.date_done.isnot(None), ClickUpTask.date_done >= close_cutoff_7)
    ).scalar() or 0)
    closed_prior_7 = int(db.execute(
        select(func.count(ClickUpTask.id))
        .where(
            ClickUpTask.date_done.isnot(None),
            ClickUpTask.date_done >= close_cutoff_14,
            ClickUpTask.date_done < close_cutoff_7,
        )
    ).scalar() or 0)
    clickup_velocity = {
        "closed_last_7": closed_last_7,
        "closed_prior_7": closed_prior_7,
        "wow_delta": closed_last_7 - closed_prior_7,
    }

    # --- Tagging compliance rate (reuse the existing endpoint's logic) ---
    compliance_payload: Optional[dict[str, Any]] = None
    try:
        from app.api.routes.clickup import clickup_compliance
        c = clickup_compliance(days=14, space_id=None, db=db)
        compliance_payload = {
            "taxonomy_configured": c.get("taxonomy_configured", False),
            "rate_closed_in_window": (c.get("closed_in_window") or {}).get("rate"),
            "rate_open_now": (c.get("open_now") or {}).get("rate"),
            "wow_delta_rate": c.get("wow_delta_rate"),
            "total_closed_in_window": (c.get("closed_in_window") or {}).get("total"),
        }
    except Exception:
        logger.exception("compliance lookup failed (non-fatal)")

    # --- Most-reacted Slack message in last 24h --------------------------
    hot_msg = db.execute(
        select(SlackMessage)
        .where(
            SlackMessage.is_deleted == False,  # noqa: E712
            SlackMessage.ts_dt >= since_24h,
            SlackMessage.reaction_count > 0,
        )
        .order_by(SlackMessage.reaction_count.desc())
        .limit(1)
    ).scalars().first()
    slack_hot = None
    if hot_msg:
        user_name = None
        if hot_msg.user_id:
            u = db.execute(select(SlackUser).where(SlackUser.user_id == hot_msg.user_id)).scalars().first()
            if u:
                user_name = u.display_name or u.real_name or u.name
        slack_hot = {
            "channel_id": hot_msg.channel_id,
            "user_name": user_name or hot_msg.user_id,
            "reactions": int(hot_msg.reaction_count or 0),
            "text": (hot_msg.text or "")[:240],
            "ts_dt": hot_msg.ts_dt.isoformat() if hot_msg.ts_dt else None,
        }

    # --- Headline counts at a glance -------------------------------------
    headline = {
        "drafts_awaiting_review": total_drafts,
        "critical_signals_24h": len(critical_payload),
        "overdue_urgent_or_high": len(stale_payload),
        "revenue_wow_pct": revenue_payload["wow_pct"],
        "clickup_wow_delta": clickup_velocity["wow_delta"],
    }

    return {
        "generated_at": now.isoformat(),
        "business_date": today_local.isoformat(),
        "headline": headline,
        "drafts": drafts_payload,
        "critical_signals": critical_payload,
        "stale_tasks": stale_payload,
        "revenue": revenue_payload,
        "clickup_velocity": clickup_velocity,
        "telemetry": telemetry_payload,
        "compliance": compliance_payload,
        "slack_hot": slack_hot,
    }
