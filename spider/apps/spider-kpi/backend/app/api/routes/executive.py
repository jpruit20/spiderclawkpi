"""Executive — single aggregated "morning brief" endpoint.

``GET /api/executive/morning`` pulls the top N items across every integrated
source so Joseph has one screen to open at 8am and know what needs attention.
Nothing new is computed — it's pure synthesis of already-materialized data.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_dashboard_session
from app.models import (
    AIInsight,
    ClickUpTask,
    DeciDecision,
    FreshdeskTicket,
    IssueSignal,
    KPIDaily,
    SlackMessage,
    SlackUser,
    TelemetryAnomaly,
    TelemetryHistoryDaily,
    TelemetryReport,
    TelemetrySession,
)
from app.services.wismo_classifier import classify_wismo


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

    # --- WISMO headline (last 7 days vs prior 7) -------------------------
    # Lightweight scan — just count, don't build full payload.
    from app.services.wismo_classifier import classify_wismo as _cw
    wismo_since = now - timedelta(days=14)
    recent_tickets = db.execute(
        select(FreshdeskTicket.subject, FreshdeskTicket.tags_json, FreshdeskTicket.raw_payload, FreshdeskTicket.created_at_source)
        .where(FreshdeskTicket.created_at_source >= wismo_since)
    ).all()
    wismo_last_7 = 0
    wismo_prior_7 = 0
    wow_cutoff = now - timedelta(days=7)
    for subj, tags, raw, ts in recent_tickets:
        if ts is None:
            continue
        desc = ""
        if isinstance(raw, dict):
            desc = raw.get("description_text") or raw.get("structured_description") or ""
            if not isinstance(desc, str):
                desc = str(desc)
        t_list = tags if isinstance(tags, list) else []
        if _cw(subj, desc, t_list).is_wismo:
            if ts >= wow_cutoff:
                wismo_last_7 += 1
            else:
                wismo_prior_7 += 1
    wismo_payload = {
        "last_7": wismo_last_7,
        "prior_7": wismo_prior_7,
        "delta": wismo_last_7 - wismo_prior_7,
    }

    # --- Telemetry anomalies (trailing-14d median/MAD z-score) -----------
    anomaly_rows = db.execute(
        select(TelemetryAnomaly)
        .where(TelemetryAnomaly.status != "dismissed")
        .order_by(TelemetryAnomaly.business_date.desc(), TelemetryAnomaly.severity.desc(), TelemetryAnomaly.id.desc())
        .limit(12)
    ).scalars().all()
    anomalies_payload = [
        {
            "id": a.id,
            "business_date": a.business_date.isoformat(),
            "metric": a.metric,
            "value": float(a.value),
            "baseline_median": float(a.baseline_median),
            "modified_z_score": float(a.modified_z_score),
            "direction": a.direction,
            "severity": a.severity,
            "summary": a.summary,
        }
        for a in anomaly_rows[:6]
    ]

    # --- AI Insights (latest cross-source observations) ------------------
    insights_rows = db.execute(
        select(AIInsight)
        .where(AIInsight.status != "dismissed")
        .order_by(AIInsight.business_date.desc(), AIInsight.confidence.desc(), AIInsight.id.desc())
        .limit(8)
    ).scalars().all()
    # Keep only the most recent business_date worth, up to 5
    insights_payload: list[dict[str, Any]] = []
    latest_date = insights_rows[0].business_date if insights_rows else None
    for r in insights_rows:
        if latest_date is not None and r.business_date < latest_date - timedelta(days=2):
            continue
        insights_payload.append({
            "id": r.id,
            "business_date": r.business_date.isoformat(),
            "title": r.title,
            "observation": r.observation,
            "confidence": float(r.confidence or 0),
            "urgency": r.urgency,
            "evidence": r.evidence_json or [],
            "suggested_action": r.suggested_action,
            "sources_used": r.sources_used or [],
            "status": r.status,
        })
        if len(insights_payload) >= 5:
            break

    # --- Headline counts at a glance -------------------------------------
    headline = {
        "drafts_awaiting_review": total_drafts,
        "critical_signals_24h": len(critical_payload),
        "overdue_urgent_or_high": len(stale_payload),
        "revenue_wow_pct": revenue_payload["wow_pct"],
        "clickup_wow_delta": clickup_velocity["wow_delta"],
        "insights_count": len(insights_payload),
        "insights_high_urgency": sum(1 for i in insights_payload if i["urgency"] == "high"),
        "anomalies_count": len(anomalies_payload),
        "anomalies_critical": sum(1 for a in anomalies_payload if a["severity"] == "critical"),
        "wismo_last_7": wismo_last_7,
        "wismo_wow_delta": wismo_last_7 - wismo_prior_7,
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
        "insights": insights_payload,
        "anomalies": anomalies_payload,
        "wismo": wismo_payload,
    }


@router.get("/insights")
def list_insights(
    limit: int = 20,
    include_dismissed: bool = False,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """All recent AI insights, newest first. Used by the Insights detail view."""
    q = select(AIInsight).order_by(AIInsight.business_date.desc(), AIInsight.id.desc())
    if not include_dismissed:
        q = q.where(AIInsight.status != "dismissed")
    rows = db.execute(q.limit(limit)).scalars().all()
    return {
        "count": len(rows),
        "insights": [
            {
                "id": r.id,
                "business_date": r.business_date.isoformat(),
                "title": r.title,
                "observation": r.observation,
                "confidence": float(r.confidence or 0),
                "urgency": r.urgency,
                "evidence": r.evidence_json or [],
                "suggested_action": r.suggested_action,
                "sources_used": r.sources_used or [],
                "status": r.status,
                "model": r.model,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


def _report_payload(r: TelemetryReport, full_body: bool) -> dict[str, Any]:
    out = {
        "id": r.id,
        "report_date": r.report_date.isoformat(),
        "report_type": r.report_type,
        "window_start": r.window_start.isoformat(),
        "window_end": r.window_end.isoformat(),
        "title": r.title,
        "summary": r.summary,
        "sections": r.sections_json or [],
        "benchmarks": r.benchmarks_json or {},
        "key_findings": r.key_findings_json or [],
        "recommendations": r.recommendations_json or [],
        "sources_used": r.sources_used or [],
        "model": r.model,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
    if full_body:
        out["body_markdown"] = r.body_markdown
    return out


@router.get("/telemetry-reports")
def list_telemetry_reports(
    limit: int = 10,
    type: Optional[str] = None,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    q = select(TelemetryReport).where(TelemetryReport.status == "published")
    if type:
        q = q.where(TelemetryReport.report_type == type)
    q = q.order_by(TelemetryReport.report_date.desc(), TelemetryReport.id.desc()).limit(limit)
    rows = db.execute(q).scalars().all()
    return {"count": len(rows), "reports": [_report_payload(r, full_body=False) for r in rows]}


@router.get("/telemetry-reports/latest")
def latest_telemetry_report(
    type: str = "comprehensive",
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    r = db.execute(
        select(TelemetryReport)
        .where(TelemetryReport.status == "published", TelemetryReport.report_type == type)
        .order_by(TelemetryReport.report_date.desc(), TelemetryReport.id.desc())
        .limit(1)
    ).scalars().first()
    if r is None:
        return {"ok": False, "reason": "no_report_of_type"}
    return {"ok": True, "report": _report_payload(r, full_body=True)}


@router.get("/telemetry-reports/{report_id}")
def get_telemetry_report(
    report_id: int,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    r = db.get(TelemetryReport, report_id)
    if r is None:
        return {"ok": False, "reason": "not_found"}
    return {"ok": True, "report": _report_payload(r, full_body=True)}


@router.get("/wismo-kpi")
def wismo_kpi(
    days: int = 30,
    recent_limit: int = 15,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """WISMO ("where is my order") customer-follow-up KPI.

    Target: trend to zero. Every WISMO ticket represents a missed
    proactive-communication opportunity — the customer shouldn't have
    needed to reach out at all.

    Returns count + rate-per-100-orders over the window, daily trend,
    week-over-week delta, and the most recent flagged tickets.
    """
    days = max(1, min(days, 365))
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=days)

    # Pull all tickets in window; classify in Python (fast enough at ~1k tickets).
    tickets = db.execute(
        select(FreshdeskTicket)
        .where(FreshdeskTicket.created_at_source >= window_start)
        .order_by(FreshdeskTicket.created_at_source.desc())
    ).scalars().all()

    wismo_tickets: list[tuple[FreshdeskTicket, Any]] = []
    daily_wismo: dict[str, int] = {}
    total_in_window = 0
    for t in tickets:
        total_in_window += 1
        desc = ""
        if isinstance(t.raw_payload, dict):
            desc = t.raw_payload.get("description_text") or t.raw_payload.get("structured_description") or ""
            if not isinstance(desc, str):
                desc = str(desc)
        tags = t.tags_json if isinstance(t.tags_json, list) else []
        result = classify_wismo(t.subject, desc, tags)
        if result.is_wismo:
            wismo_tickets.append((t, result))
            if t.created_at_source:
                d = t.created_at_source.date().isoformat()
                daily_wismo[d] = daily_wismo.get(d, 0) + 1

    # Orders in window (for rate).
    orders_in_window = int(db.execute(
        select(func.sum(KPIDaily.orders))
        .where(KPIDaily.business_date >= window_start.date())
    ).scalar() or 0)
    rate_per_100 = (len(wismo_tickets) / orders_in_window * 100.0) if orders_in_window > 0 else None

    # Daily trend — one row per day in the window, even if 0 WISMOs.
    trend = []
    orders_by_date = {
        r.business_date.isoformat(): int(r.orders or 0)
        for r in db.execute(
            select(KPIDaily.business_date, KPIDaily.orders)
            .where(KPIDaily.business_date >= window_start.date())
        ).all()
    }
    start_date = window_start.date()
    for i in range(days):
        d = (start_date + timedelta(days=i)).isoformat()
        trend.append({
            "date": d,
            "wismo": daily_wismo.get(d, 0),
            "orders": orders_by_date.get(d, 0),
        })

    # Week-over-week.
    wow_cutoff = now - timedelta(days=7)
    wow_prior_cutoff = now - timedelta(days=14)
    last_7 = sum(1 for (t, _r) in wismo_tickets if t.created_at_source and t.created_at_source >= wow_cutoff)
    prior_7 = sum(1 for (t, _r) in wismo_tickets if t.created_at_source and wow_prior_cutoff <= t.created_at_source < wow_cutoff)
    wow_delta_pct: Optional[float] = None
    if prior_7 > 0:
        wow_delta_pct = (last_7 - prior_7) / prior_7 * 100.0

    # Recent flagged tickets with links.
    freshdesk_domain = os.environ.get("FRESHDESK_DOMAIN") or ""
    recent_payload = []
    for (t, r) in wismo_tickets[:recent_limit]:
        ticket_url: Optional[str] = None
        if freshdesk_domain and t.ticket_id:
            base = freshdesk_domain.rstrip("/")
            if not base.startswith("http"):
                base = f"https://{base}"
            ticket_url = f"{base}/a/tickets/{t.ticket_id}"
        recent_payload.append({
            "ticket_id": t.ticket_id,
            "subject": t.subject,
            "created_at": t.created_at_source.isoformat() if t.created_at_source else None,
            "status": t.status,
            "priority": t.priority,
            "requester_id": t.requester_id,
            "confidence": r.confidence,
            "matched_rule": r.matched_rule,
            "url": ticket_url,
        })

    return {
        "ok": True,
        "generated_at": now.isoformat(),
        "window_days": days,
        "window_start": window_start.date().isoformat(),
        "tickets_in_window": total_in_window,
        "wismo_count": len(wismo_tickets),
        "wismo_pct_of_tickets": round(len(wismo_tickets) / total_in_window * 100.0, 1) if total_in_window else 0.0,
        "orders_in_window": orders_in_window,
        "rate_per_100_orders": round(rate_per_100, 2) if rate_per_100 is not None else None,
        "trend": trend,
        "week_over_week": {
            "last_7": last_7,
            "prior_7": prior_7,
            "delta_pct": round(wow_delta_pct, 1) if wow_delta_pct is not None else None,
        },
        "recent_tickets": recent_payload,
    }


@router.get("/firmware-cohorts")
def firmware_cohorts(
    min_sessions: int = 20,
    limit: int = 20,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Per-firmware session performance (cook success, stability, tts, error rate).

    Operates over the full telemetry_sessions table. Returns a list of
    cohorts with n ≥ min_sessions, sorted by session count desc.

    Returns ``{ok: False, reason: "insufficient_data"}`` when session
    table has <100 rows so callers can show a "backfill in progress"
    hint instead of an empty chart.
    """
    total = int(db.execute(select(func.count(TelemetrySession.id))).scalar() or 0)
    if total < 100:
        return {
            "ok": False,
            "reason": "insufficient_data",
            "total_sessions": total,
            "hint": "Session-level data is still backfilling from S3. This panel will populate automatically once the v2 backfill completes.",
        }

    rows = db.execute(text("""
        SELECT firmware_version,
               COUNT(*)                                AS n,
               AVG((cook_success::int))::float         AS success_rate,
               AVG(temp_stability_score)::float        AS avg_stability,
               AVG(session_duration_seconds)::float    AS avg_duration_seconds,
               AVG(time_to_stabilization_seconds)::float AS avg_tts_seconds,
               SUM(error_count)                        AS total_errors,
               SUM(CASE WHEN error_count > 0 THEN 1 ELSE 0 END) AS sessions_with_errors,
               AVG(target_temp)::float                 AS avg_target_temp,
               MIN(session_start)                      AS first_seen,
               MAX(session_start)                      AS last_seen
          FROM telemetry_sessions
         WHERE firmware_version IS NOT NULL
         GROUP BY firmware_version
         HAVING COUNT(*) >= :min_n
         ORDER BY n DESC
         LIMIT :limit
    """), {"min_n": min_sessions, "limit": limit}).mappings().all()

    cohorts = []
    for r in rows:
        n = int(r["n"] or 0)
        errors = int(r["sessions_with_errors"] or 0)
        cohorts.append({
            "firmware_version": r["firmware_version"],
            "sessions": n,
            "success_rate": float(r["success_rate"] or 0),
            "avg_stability": float(r["avg_stability"] or 0),
            "avg_duration_seconds": float(r["avg_duration_seconds"] or 0),
            "avg_tts_seconds": float(r["avg_tts_seconds"]) if r["avg_tts_seconds"] is not None else None,
            "error_session_rate": (errors / n) if n else 0.0,
            "total_errors": int(r["total_errors"] or 0),
            "avg_target_temp": float(r["avg_target_temp"]) if r["avg_target_temp"] is not None else None,
            "first_seen": r["first_seen"].isoformat() if r["first_seen"] else None,
            "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
        })
    return {
        "ok": True,
        "total_sessions": total,
        "cohorts_returned": len(cohorts),
        "min_sessions_threshold": min_sessions,
        "cohorts": cohorts,
    }


@router.post("/insights/{insight_id}/dismiss")
def dismiss_insight(
    insight_id: int,
    reason: Optional[str] = None,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    row = db.get(AIInsight, insight_id)
    if row is None:
        return {"ok": False, "reason": "not_found"}
    row.status = "dismissed"
    if reason:
        row.dismissed_reason = reason[:2000]
    db.commit()
    return {"ok": True, "id": insight_id}
