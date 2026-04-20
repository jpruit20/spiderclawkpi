"""Cross-source daily insight engine.

Once a day at dawn, walks every integrated data source (telemetry, orders,
support, internal ops, social) and compiles a structured **context document**.
The document is handed to Claude Opus 4.7 with adaptive thinking + effort=max;
Opus returns 3-5 non-obvious cross-source observations (correlations,
causation, emerging themes) in a validated Pydantic schema.

Output rows land in ``ai_insights`` and surface on the morning brief + email.

Design principles:
  * **Cross-source only.** Single-source observations are what the existing
    dashboard blocks already show. The prompt is explicit: surface things a
    human reading *one* source at a time would miss.
  * **Evidence-backed.** Every insight carries a list of concrete data points
    from the context so Joseph can verify.
  * **Fail-silent.** Missing ANTHROPIC_API_KEY or a Claude error logs + skips.
    No dashboard data is blocked on insights generation.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import Session

from sqlalchemy import text

from app.core.config import get_settings
from app.models import (
    AIInsight,
    BetaCohortMember,
    ClickUpTask,
    ClickUpTasksDaily,
    FirmwareIssueTag,
    FirmwareRelease,
    FreshdeskTicket,
    FreshdeskTicketsDaily,
    IssueSignal,
    KPIDaily,
    LoreEvent,
    ReviewMention,
    SlackActivityDaily,
    SlackMessage,
    SocialMention,
    TelemetryHistoryDaily,
)
from app.services.seasonality import metric_context


# Shadow-signal SQL templates — parallels beta_cohort._SHADOW_DETECTORS
# but returns a single fleet-wide session count per window. Kept inline
# (rather than imported) so the context builder can ask "how many times
# did this signature fire across the whole fleet?" without depending on
# beta_cohort's per-device output shape.
_TREND_COUNT_QUERIES: dict[str, str] = {
    "persistent_overshoot": """
        SELECT COUNT(*) FROM telemetry_sessions
         WHERE session_start >= :start AND session_start < :end
           AND max_overshoot_f >= 25 AND cook_outcome = 'reached_not_held'
    """,
    "persistent_undershoot": """
        SELECT COUNT(*) FROM telemetry_sessions
         WHERE session_start >= :start AND session_start < :end
           AND max_undershoot_f >= 25
           AND cook_outcome IN ('reached_not_held','did_not_reach')
    """,
    "slow_recovery": """
        SELECT COUNT(*) FROM telemetry_sessions
         WHERE session_start >= :start AND session_start < :end
           AND avg_recovery_seconds >= 300
    """,
    "startup_fail": """
        SELECT COUNT(*) FROM telemetry_sessions
         WHERE session_start >= :start AND session_start < :end
           AND cook_outcome = 'did_not_reach'
           AND cook_intent IN ('short_cook','medium_cook','long_cook')
    """,
    "wifi_disconnect": """
        SELECT COUNT(*) FROM telemetry_sessions
         WHERE session_start >= :start AND session_start < :end
           AND cook_outcome = 'disconnect'
    """,
    "oscillation": """
        SELECT COUNT(*) FROM telemetry_sessions
         WHERE session_start >= :start AND session_start < :end
           AND disturbance_count >= 8
           AND in_control_pct IS NOT NULL AND in_control_pct < 0.5
    """,
    "probe_dropout": """
        SELECT COUNT(*) FROM telemetry_sessions
         WHERE session_start >= :start AND session_start < :end
           AND disconnect_events > 0 AND error_count = 0
    """,
    "error_code_42": """
        SELECT COUNT(*) FROM telemetry_sessions
         WHERE session_start >= :start AND session_start < :end
           AND error_codes_json @> '[42]'::jsonb
    """,
}


logger = logging.getLogger(__name__)
settings = get_settings()
BUSINESS_TZ = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Pydantic schema for structured output
# ---------------------------------------------------------------------------

Urgency = Literal["high", "medium", "low"]


class Insight(BaseModel):
    title: str = Field(max_length=160, description="Headline-style, 5-12 words.")
    observation: str = Field(
        max_length=1200,
        description="2-3 sentences explaining what you noticed, with specific numbers. Plain English.",
    )
    confidence: float = Field(ge=0.0, le=1.0)
    urgency: Urgency
    evidence: list[str] = Field(
        default_factory=list,
        description="3-6 bullet points citing the data points that led to this observation. Include specific dates and numbers.",
    )
    sources_used: list[str] = Field(
        default_factory=list,
        description="Which data sources contributed (e.g. 'telemetry', 'freshdesk', 'shopify', 'clickup', 'slack').",
    )
    suggested_action: str = Field(
        max_length=400,
        description="One concrete next step a leader could take this week. Avoid vague advice.",
    )


class InsightsBundle(BaseModel):
    insights: list[Insight] = Field(
        min_length=0,
        max_length=7,
        description="3-5 non-obvious cross-source observations. Fewer if the data is genuinely quiet.",
    )


# ---------------------------------------------------------------------------
# Context builder — compiles a structured digest of everything we know
# ---------------------------------------------------------------------------

def _fmt_pct(v: Optional[float]) -> str:
    return f"{v * 100:.1f}%" if v is not None else "—"


def _fmt_currency(v: Optional[float]) -> str:
    return f"${v:,.0f}" if v is not None else "—"


def build_context(db: Session, lookback_days: int = 30) -> tuple[str, list[str]]:
    """Compile the cross-source context document Opus will read.

    Returns (context_string, sources_included). Sections are terse because
    dense > verbose for LLM reasoning — the model does better with tabular
    summaries than prose.
    """
    today = datetime.now(BUSINESS_TZ).date()
    start = today - timedelta(days=lookback_days)
    prior_start = today - timedelta(days=lookback_days * 2)

    lines: list[str] = []
    sources: list[str] = []

    lines.append(f"=== Spider Grills daily context — generated {today.isoformat()} ===")
    lines.append(f"Spider Grills makes the Venom temperature controller (works on Weber kettles + their Huntsman and Giant Huntsman grills). Direct-to-consumer, Shopify + Amazon. Support via Freshdesk. Internal ops in ClickUp + Slack. ~1800 MAU on the Venom app.")
    lines.append("")
    lines.append(f"Analysis window: last {lookback_days} days ({start} to {today}).")
    lines.append("")

    # --- REVENUE ----------------------------------------------------------
    kpi_rows = db.execute(
        select(KPIDaily).where(KPIDaily.business_date >= prior_start).order_by(KPIDaily.business_date)
    ).scalars().all()
    if kpi_rows:
        sources.append("shopify/revenue")
        cur = [r for r in kpi_rows if r.business_date >= start]
        prev = [r for r in kpi_rows if r.business_date < start]
        rev_cur = sum(float(r.revenue or 0) for r in cur)
        rev_prev = sum(float(r.revenue or 0) for r in prev)
        orders_cur = sum(int(r.orders or 0) for r in cur)
        orders_prev = sum(int(r.orders or 0) for r in prev)
        aov_cur = (rev_cur / orders_cur) if orders_cur else None
        aov_prev = (rev_prev / orders_prev) if orders_prev else None
        rev_delta_pct = ((rev_cur - rev_prev) / rev_prev * 100.0) if rev_prev else None
        lines.append("## REVENUE (Shopify)")
        lines.append(f"  - Current {lookback_days}d total: {_fmt_currency(rev_cur)} ({orders_cur} orders, AOV {_fmt_currency(aov_cur)})")
        lines.append(f"  - Prior {lookback_days}d total:   {_fmt_currency(rev_prev)} ({orders_prev} orders, AOV {_fmt_currency(aov_prev)})")
        if rev_delta_pct is not None:
            lines.append(f"  - Period-over-period: {rev_delta_pct:+.1f}% revenue")
        # Daily sparkline (last 30 days)
        last30 = cur[-30:] if len(cur) > 30 else cur
        if last30:
            lines.append(f"  - Daily revenue (last {len(last30)} days):")
            for r in last30:
                lines.append(f"      {r.business_date.isoformat()}  rev={_fmt_currency(float(r.revenue or 0))}  orders={r.orders or 0}  csat={r.csat or 0:.2f}  tickets_created={r.tickets_created or 0}")
        lines.append("")

    # --- TELEMETRY --------------------------------------------------------
    tel_rows = db.execute(
        select(TelemetryHistoryDaily)
        .where(TelemetryHistoryDaily.business_date >= prior_start)
        .order_by(TelemetryHistoryDaily.business_date)
    ).scalars().all()
    if tel_rows:
        sources.append("telemetry/dynamodb")
        lines.append("## VENOM FLEET TELEMETRY (DynamoDB-derived)")
        cur_t = [r for r in tel_rows if r.business_date >= start]
        if cur_t:
            avg_active = sum(r.active_devices for r in cur_t) / len(cur_t)
            total_sessions = sum(r.session_count or 0 for r in cur_t)
            total_successful = sum(r.successful_sessions or 0 for r in cur_t)
            overall_cook_success = (total_successful / total_sessions) if total_sessions else None
            total_events = sum(r.total_events for r in cur_t)
            total_errors = sum(r.error_events for r in cur_t)
            overall_err = (total_errors / total_events) if total_events else None
            lines.append(f"  - Avg active devices/day: {avg_active:.0f}")
            lines.append(f"  - Total cook sessions: {total_sessions}, successful: {total_successful} (cook success {_fmt_pct(overall_cook_success)})")
            lines.append(f"  - Total events: {total_events}, errors: {total_errors} (error rate {_fmt_pct(overall_err)})")
            # Firmware distribution (aggregate across window)
            fw_totals: Counter = Counter()
            model_totals: Counter = Counter()
            for r in cur_t:
                for k, v in (r.firmware_distribution or {}).items():
                    fw_totals[str(k)] += int(v or 0)
                for k, v in (r.model_distribution or {}).items():
                    model_totals[str(k)] += int(v or 0)
            if fw_totals:
                top_fw = fw_totals.most_common(8)
                total_fw = sum(fw_totals.values())
                lines.append(f"  - Firmware distribution (by event count): " + ", ".join(f"{fw}={n} ({n/total_fw*100:.0f}%)" for fw, n in top_fw))
            if model_totals:
                top_m = model_totals.most_common(6)
                lines.append(f"  - Model mix: " + ", ".join(f"{m}={n}" for m, n in top_m))
        # Per-day trend (last 21 days)
        last21 = cur_t[-21:] if len(cur_t) > 21 else cur_t
        lines.append(f"  - Daily (last {len(last21)} days):")
        for r in last21:
            cs = (r.successful_sessions / r.session_count) if (r.session_count or 0) > 0 else None
            err = (r.error_events / r.total_events) if (r.total_events or 0) > 0 else None
            lines.append(f"      {r.business_date.isoformat()}  active={r.active_devices}  sessions={r.session_count or 0}  cook_success={_fmt_pct(cs)}  err_rate={_fmt_pct(err)}")
        lines.append("")

    # --- FRESHDESK SUPPORT -----------------------------------------------
    fd_rows = db.execute(
        select(FreshdeskTicketsDaily)
        .where(FreshdeskTicketsDaily.business_date >= prior_start)
        .order_by(FreshdeskTicketsDaily.business_date)
    ).scalars().all()
    if fd_rows:
        sources.append("freshdesk")
        cur_f = [r for r in fd_rows if r.business_date >= start]
        prev_f = [r for r in fd_rows if r.business_date < start]
        lines.append("## SUPPORT (Freshdesk)")
        lines.append(f"  - Tickets created (current {lookback_days}d): {sum(r.tickets_created for r in cur_f)}")
        lines.append(f"  - Tickets created (prior {lookback_days}d):   {sum(r.tickets_created for r in prev_f)}")
        if cur_f:
            csat_vals = [r.csat for r in cur_f if r.csat]
            avg_csat = sum(csat_vals) / len(csat_vals) if csat_vals else None
            lines.append(f"  - Avg CSAT current window: {avg_csat:.2f}" if avg_csat else "  - CSAT: no data")
            lines.append(f"  - Avg first-response hrs: {sum(r.first_response_hours for r in cur_f if r.first_response_hours) / max(1, sum(1 for r in cur_f if r.first_response_hours)):.1f}")
        # Top tags from actual tickets
        recent_tickets = db.execute(
            select(FreshdeskTicket).where(FreshdeskTicket.created_at_source >= datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc))
        ).scalars().all()
        if recent_tickets:
            tag_counter: Counter = Counter()
            for t in recent_tickets:
                for tag in (t.tags_json or []):
                    if tag:
                        tag_counter[str(tag)] += 1
            top_tags = tag_counter.most_common(10)
            if top_tags:
                lines.append(f"  - Top ticket tags (current window): " + ", ".join(f"{tag}({n})" for tag, n in top_tags))
        lines.append("")

    # --- CLICKUP ACTIVITY (including campaign launches + firmware releases)
    cu_daily = db.execute(
        select(ClickUpTasksDaily)
        .where(ClickUpTasksDaily.business_date >= prior_start)
        .order_by(ClickUpTasksDaily.business_date)
    ).scalars().all()
    if cu_daily:
        sources.append("clickup")
        cur_c = [r for r in cu_daily if r.business_date >= start]
        prev_c = [r for r in cu_daily if r.business_date < start]
        lines.append("## INTERNAL WORK (ClickUp)")
        lines.append(f"  - Tasks closed current {lookback_days}d: {sum(r.tasks_completed for r in cur_c)} (prior: {sum(r.tasks_completed for r in prev_c)})")
        lines.append(f"  - Tasks created current {lookback_days}d: {sum(r.tasks_created for r in cur_c)}")

        # Recent campaign launches (Category=Campaign) with due dates in window
        campaign_tasks = db.execute(
            select(ClickUpTask).where(
                ClickUpTask.due_date.isnot(None),
                ClickUpTask.due_date >= datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc),
                ClickUpTask.due_date <= datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc),
            )
        ).scalars().all()
        # Filter by Category=Campaign via custom fields
        cam_hits = []
        for t in campaign_tasks:
            for f in (t.custom_fields_json or []):
                if isinstance(f, dict) and (f.get("name") or "").lower() == "category":
                    type_cfg = f.get("type_config") or {}
                    opts = type_cfg.get("options") or []
                    val = f.get("value")
                    label = None
                    if isinstance(val, int) and 0 <= val < len(opts):
                        label = (opts[val] or {}).get("name")
                    elif isinstance(val, str):
                        for o in opts:
                            if isinstance(o, dict) and (o.get("id") == val):
                                label = o.get("name")
                                break
                    if label and label.lower() == "campaign":
                        cam_hits.append(t)
                        break
        if cam_hits:
            lines.append(f"  - Campaign launch dates in window ({len(cam_hits)}):")
            for t in sorted(cam_hits, key=lambda x: x.due_date):
                lines.append(f"      {t.due_date.date().isoformat()}  {t.name or '?'}")

        # Recent firmware completions (Category=Firmware)
        fw_done = db.execute(
            select(ClickUpTask).where(
                ClickUpTask.date_done.isnot(None),
                ClickUpTask.date_done >= datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc),
            )
        ).scalars().all()
        fw_hits = []
        for t in fw_done:
            for f in (t.custom_fields_json or []):
                if isinstance(f, dict) and (f.get("name") or "").lower() == "category":
                    type_cfg = f.get("type_config") or {}
                    opts = type_cfg.get("options") or []
                    val = f.get("value")
                    label = None
                    if isinstance(val, int) and 0 <= val < len(opts):
                        label = (opts[val] or {}).get("name")
                    elif isinstance(val, str):
                        for o in opts:
                            if isinstance(o, dict) and (o.get("id") == val):
                                label = o.get("name")
                                break
                    if label and label.lower() == "firmware":
                        fw_hits.append(t)
                        break
        if fw_hits:
            lines.append(f"  - Firmware-category tasks completed in window ({len(fw_hits)}):")
            for t in sorted(fw_hits, key=lambda x: x.date_done):
                lines.append(f"      {t.date_done.date().isoformat()}  {t.name or '?'}")
        lines.append("")

    # --- SLACK / ISSUE SIGNALS -------------------------------------------
    sig_rows = db.execute(
        select(IssueSignal).where(IssueSignal.created_at >= datetime.now(timezone.utc) - timedelta(days=lookback_days))
    ).scalars().all()
    if sig_rows:
        sources.append("slack+issue_radar")
        by_type: Counter = Counter()
        by_source: Counter = Counter()
        critical_titles: list[str] = []
        ai_real_issues: list[str] = []
        for s in sig_rows:
            by_type[s.signal_type or "?"] += 1
            by_source[s.source or "?"] += 1
            meta = s.metadata_json or {}
            ai = meta.get("ai") if isinstance(meta, dict) else None
            if isinstance(ai, dict) and ai.get("classification") == "real_issue":
                if ai.get("title"):
                    ai_real_issues.append(f"{s.source}: {ai['title']}")
            if (s.severity or "").lower() == "critical":
                if isinstance(ai, dict) and ai.get("title"):
                    critical_titles.append(f"[{s.source}] {ai['title']}")
                elif s.title:
                    critical_titles.append(f"[{s.source}] {s.title[:80]}")
        lines.append("## SIGNALS DETECTED (Issue Radar + Slack/ClickUp scanners)")
        lines.append(f"  - Total in window: {len(sig_rows)} by source: " + ", ".join(f"{k}={v}" for k, v in by_source.most_common()))
        lines.append(f"  - Top signal types: " + ", ".join(f"{t}({n})" for t, n in by_type.most_common(10)))
        if critical_titles:
            lines.append(f"  - Critical-severity items ({len(critical_titles)}):")
            for title in critical_titles[:15]:
                lines.append(f"      - {title}")
        if ai_real_issues:
            lines.append(f"  - AI-classified real_issue items (first 10):")
            for t in ai_real_issues[:10]:
                lines.append(f"      - {t}")
        lines.append("")

    # --- SOCIAL / VOICE OF CUSTOMER --------------------------------------
    # Review mentions (Amazon/Google)
    reviews = db.execute(
        select(ReviewMention).where(
            ReviewMention.published_at >= datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
        )
    ).scalars().all()
    if reviews:
        sources.append("reviews")
        by_source_r: Counter = Counter(r.source or "?" for r in reviews)
        neg = [r for r in reviews if (r.sentiment or "").lower() in {"negative", "very_negative"}]
        lines.append("## CUSTOMER REVIEWS (Amazon + Google)")
        lines.append(f"  - Total mentions: {len(reviews)} by source: " + ", ".join(f"{k}={v}" for k, v in by_source_r.most_common()))
        if reviews:
            avg_rating = sum(float(r.rating or 0) for r in reviews if r.rating) / max(1, sum(1 for r in reviews if r.rating))
            lines.append(f"  - Avg rating: {avg_rating:.2f} (of {sum(1 for r in reviews if r.rating)} rated)")
        if neg:
            lines.append(f"  - Negative reviews ({len(neg)}):")
            for r in neg[:8]:
                body = (r.body or "")[:140].replace("\n", " ")
                lines.append(f"      [{r.source}] rating={r.rating} {body}")
        lines.append("")

    # Social mentions (Reddit etc)
    socials = db.execute(
        select(SocialMention).where(
            SocialMention.published_at >= datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
        )
    ).scalars().all()
    if socials:
        sources.append("social")
        by_platform: Counter = Counter(s.platform or "?" for s in socials)
        lines.append("## SOCIAL MENTIONS (Reddit + YouTube)")
        lines.append(f"  - Total: {len(socials)} by platform: " + ", ".join(f"{k}={v}" for k, v in by_platform.most_common()))
        neg_soc = [s for s in socials if (s.sentiment or "").lower() in {"negative", "very_negative"}]
        if neg_soc:
            lines.append(f"  - Negative mentions ({len(neg_soc)}):")
            for s in neg_soc[:5]:
                body = (s.body or s.title or "")[:140].replace("\n", " ")
                lines.append(f"      [{s.platform}/{s.subreddit or '?'}] {body}")
        lines.append("")

    # --- SLACK ACTIVITY PULSE --------------------------------------------
    slack_daily = db.execute(
        select(SlackActivityDaily).where(SlackActivityDaily.business_date >= start).order_by(SlackActivityDaily.business_date.desc())
    ).scalars().all()
    if slack_daily:
        sources.append("slack")
        by_ch: dict[str, dict[str, int]] = defaultdict(lambda: {"msgs": 0, "reactions": 0})
        for r in slack_daily:
            if not r.channel_name:
                continue
            by_ch[r.channel_name]["msgs"] += int(r.message_count or 0)
            by_ch[r.channel_name]["reactions"] += int(r.reaction_count or 0)
        if by_ch:
            lines.append("## SLACK CHANNEL ACTIVITY")
            sorted_ch = sorted(by_ch.items(), key=lambda kv: -kv[1]["msgs"])
            for name, vals in sorted_ch[:8]:
                lines.append(f"  - #{name}: {vals['msgs']} msgs, {vals['reactions']} reactions")
            lines.append("")

    # --- LORE EVENTS (company timeline) ----------------------------------
    # Range-overlap: event (start_date, end_date) intersects [start, today].
    # end_date NULL = single-day; treat as a point event.
    lore_rows = db.execute(
        select(LoreEvent)
        .where(
            or_(
                LoreEvent.end_date >= start,
                and_(LoreEvent.end_date.is_(None), LoreEvent.start_date >= start),
            ),
            LoreEvent.start_date <= today,
        )
        .order_by(LoreEvent.start_date.desc())
    ).scalars().all()
    if lore_rows:
        sources.append("lore")
        lines.append("## LORE EVENTS (last {}d — launches, incidents, campaigns, firmware, promotions)".format(lookback_days))
        lines.append("  Use these to explain anomalies. If a metric shifts within 3 days of an event, cite the event.")
        for ev in lore_rows[:40]:
            span = ev.start_date.isoformat()
            if ev.end_date and ev.end_date != ev.start_date:
                span += f"→{ev.end_date.isoformat()}"
            div = ev.division or "company"
            conf = "" if ev.confidence == "confirmed" else f" ({ev.confidence})"
            title = (ev.title or "")[:140]
            lines.append(f"  - [{span}] {ev.event_type}/{div}: {title}{conf}")
        if len(lore_rows) > 40:
            lines.append(f"  - …+{len(lore_rows) - 40} more in window")
        lines.append("")

    # --- SEASONAL CONTEXT (today vs prior-year baseline) -----------------
    # Latest business date for which we have KPI data (usually today-1 in ET).
    seasonal_lines: list[str] = []
    for metric_name in ("revenue", "orders", "tickets_created", "active_devices"):
        try:
            ctx = metric_context(db, metric_name, today)
        except Exception:
            ctx = None
        if ctx is None or ctx.current_value is None or ctx.year_count == 0:
            continue
        p50 = ctx.baseline.get("p50")
        delta = ctx.delta_vs_median_pct
        pct = ctx.percentile_rank
        cv_fmt = f"{ctx.current_value:,.0f}"
        p50_fmt = f"{p50:,.0f}" if p50 is not None else "—"
        delta_fmt = f"{delta:+.1f}%" if delta is not None else "—"
        pct_fmt = f"p{round(pct * 100)}" if pct is not None else "—"
        seasonal_lines.append(
            f"  - {metric_name} today: {cv_fmt} (vs p50={p50_fmt}, delta={delta_fmt}, rank={pct_fmt} vs {ctx.year_count} prior years, verdict={ctx.verdict})"
        )
    if seasonal_lines:
        sources.append("seasonality")
        lines.append("## SEASONAL CONTEXT (today vs prior-year same-day-of-year baseline)")
        lines.append("  Use this to tell 'unusual vs normal' apart. A -10% WoW drop might still be +20% above seasonal p50.")
        lines.extend(seasonal_lines)
        lines.append("")

    # --- FIRMWARE BETA PROGRAM + SHADOW-SIGNAL TRENDS --------------------
    # Fleet-wide firing counts for each issue-tag signature, last 7d vs
    # prior 7d. Surfaces "probe_dropout up 40% WoW" before it becomes a
    # support-ticket spike. Plus: active beta cohort status + release
    # verdicts so Opus can connect a regression to the release that
    # caused it.
    now_utc = datetime.now(timezone.utc)
    trend_lines: list[str] = []
    for slug, sql in _TREND_COUNT_QUERIES.items():
        cur = db.execute(text(sql), {
            "start": now_utc - timedelta(days=7),
            "end": now_utc,
        }).scalar() or 0
        prev = db.execute(text(sql), {
            "start": now_utc - timedelta(days=14),
            "end": now_utc - timedelta(days=7),
        }).scalar() or 0
        if cur == 0 and prev == 0:
            continue
        delta_pct = ((cur - prev) / prev * 100.0) if prev else None
        delta_fmt = f"{delta_pct:+.0f}%" if delta_pct is not None else "n/a"
        trend_lines.append(f"  - {slug}: {cur} firings last 7d (prior 7d {prev}, Δ {delta_fmt})")
    if trend_lines:
        sources.append("beta/shadow_signals")
        lines.append("## SHADOW-SIGNAL TRENDS (firmware issue-tag firings, fleet-wide)")
        lines.append("  Each tag is a telemetry signature matching a specific failure mode. A large WoW jump here is an early warning that often precedes Freshdesk ticket volume.")
        lines.extend(trend_lines)
        lines.append("")

    releases = db.execute(
        select(FirmwareRelease).order_by(desc(FirmwareRelease.created_at)).limit(6)
    ).scalars().all()
    if releases:
        cohort_counts_by_release = {
            r.id: dict(
                (state, int(n)) for (state, n) in db.execute(
                    select(BetaCohortMember.state, func.count(BetaCohortMember.id))
                    .where(BetaCohortMember.release_id == r.id)
                    .group_by(BetaCohortMember.state)
                ).all()
            )
            for r in releases
        }
        sources.append("beta/releases")
        lines.append("## FIRMWARE BETA PROGRAM")
        lines.append("  Recent firmware releases with their issue tags, cohort state, and post-deploy verdict health.")
        for r in releases:
            counts = cohort_counts_by_release.get(r.id, {})
            report = r.beta_report_json or {}
            health = report.get("release_health")
            tally = report.get("tally") or {}
            cohort_str = ", ".join(f"{k}={v}" for k, v in counts.items()) if counts else "no cohort"
            tally_str = ", ".join(f"{k}={v}" for k, v in tally.items()) if tally else "no verdict yet"
            health_str = f" · release_health={health}" if health else ""
            addr = ",".join(r.addresses_issues or []) or "—"
            lines.append(f"  - {r.version} ({r.status}) addresses={addr}{health_str}")
            lines.append(f"      cohort: {cohort_str}")
            lines.append(f"      verdict tally: {tally_str}")
        lines.append("")

    lines.append("=== END CONTEXT ===")
    return "\n".join(lines), sources


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are the cross-source insight engine for the Spider Grills KPI dashboard.

Every morning you receive a structured digest of the last 30 days across every data source the company has: Shopify revenue, Venom fleet telemetry (cook sessions, error rates, firmware distribution), Freshdesk support tickets, ClickUp internal work (including firmware releases and marketing campaign launch dates), detected issue signals from Slack/ClickUp with AI-classifications, customer reviews (Amazon/Google), social mentions, and Slack channel activity.

Your job is to surface **3-5 non-obvious observations** that a human reading one source at a time would miss. You exist to provide value the single-source dashboard blocks cannot — find CAUSATION and CORRELATION across sources.

**What good looks like:**
- "Support ticket volume for Huntsman thermocouple doubled between March 15-25. That window coincides with the 22,000-unit batch shipped in early March. Worth checking serial numbers on recent complaints — might be a bad component run."
- "Firmware v1.18.3 shipped 2026-03-25. Cook success rate on active devices dropped from 92% to 84% over the following 10 days, then recovered after v1.18.4 on 2026-04-06. The regression is consistent with the firmware rollout timeline, not customer behavior."
- "Campaign 'March Giveaway' launched 2026-03-09; revenue that day was $X vs 7-day trailing average $Y (+47%). But the lift didn't persist past 48 hours and return rate in the following 2 weeks was 2× normal — suggests the campaign brought one-time buyers, not repeat customers."

**What bad looks like:**
- "Revenue is up this month" — single-source, obvious from revenue chart
- "We had some critical Slack signals this week" — single-source, obvious from Issue Radar
- "Consider monitoring support tickets" — vague advice, not an observation

**Rules:**
- EVERY insight must cite at least two data sources in its evidence.
- Numbers must come from the context document. Do not invent values.
- If the data genuinely shows no non-obvious cross-source patterns, return fewer insights (3 is better than 5 stretched).
- Urgency: `high` = needs action this week, `medium` = notable but not blocking, `low` = worth tracking
- Confidence: use 0.8+ only when the correlation is strong (multiple data points + clear temporal alignment)
- Suggested action should be CONCRETE: "schedule a firmware review with Kyle" not "look into this"

**Lore events (company timeline):** The context now includes a LORE EVENTS section listing launches, incidents, campaigns, firmware, promotions, and personnel events within the analysis window. When a metric shifts within ±3 days of one of these events, CITE the event in your evidence and suggested_action. A revenue drop on the day a promotion ended is not a mystery — say so.

**Seasonal context:** The context now includes a SEASONAL CONTEXT section showing today's value for key metrics vs the prior-year baseline (p50 / percentile rank / verdict). Use this to distinguish "unusual" from "normal for this time of year". A -10% WoW drop that still sits at p70 of seasonal is not a meaningful regression; flag it only if WoW is down AND the seasonal rank also slipped.

**Shadow-signal trends + firmware beta program:** The context includes a SHADOW-SIGNAL TRENDS section — fleet-wide counts of telemetry signatures that match specific firmware failure modes (probe_dropout, persistent_overshoot, wifi_disconnect, etc.), last 7d vs prior 7d. It also includes a FIRMWARE BETA PROGRAM section with recent release profiles, cohort state, and post-deploy verdict health. These are leading indicators: a 40% jump in `probe_dropout` firings often surfaces days before the corresponding Freshdesk tickets. When a shadow signal spikes, check whether a recent firmware release (in the LORE EVENTS or FIRMWARE BETA PROGRAM sections) could be the cause. When a beta release is mid-rollout and its verdict tally leans toward `still_failing` or `regression`, flag it as high-urgency.

Be direct. Be terse. Be specific with numbers and dates."""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def is_configured() -> bool:
    return bool(settings.anthropic_api_key)


def generate_insights(db: Session, save: bool = True) -> dict[str, Any]:
    """Build context → call Opus → persist insights. Returns a summary dict."""
    if not is_configured():
        return {"ok": False, "reason": "ANTHROPIC_API_KEY not configured", "generated": 0}

    try:
        import anthropic
    except ImportError:
        return {"ok": False, "reason": "anthropic package not installed", "generated": 0}

    today = datetime.now(BUSINESS_TZ).date()

    # If we already generated insights today, don't double-bill — caller can override by deleting first.
    if save:
        existing_today = db.execute(
            select(func.count(AIInsight.id)).where(AIInsight.business_date == today)
        ).scalar()
        if existing_today:
            return {"ok": True, "reason": "already_generated_today", "generated": 0, "business_date": today.isoformat()}

    context, sources = build_context(db, lookback_days=30)
    started = datetime.now(timezone.utc)

    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        timeout=300,  # effort=max + adaptive thinking can run 2-3 min on Opus 4.7
        max_retries=1,
    )

    model_id = "claude-opus-4-7"
    try:
        # max_tokens must cover thinking + output. With effort=max + adaptive
        # thinking, Opus 4.7 can easily burn 15-20k tokens on reasoning before
        # starting to write; 8192 truncated the JSON mid-string on 2026-04-19.
        response = client.messages.parse(
            model=model_id,
            max_tokens=32000,
            thinking={"type": "adaptive"},
            output_config={"effort": "max"},
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": context}],
            output_format=InsightsBundle,
        )
    except Exception as exc:
        logger.exception("Opus call failed")
        return {"ok": False, "reason": f"api_error: {exc}", "generated": 0}

    bundle: Optional[InsightsBundle] = response.parsed_output
    if bundle is None:
        return {"ok": False, "reason": "parsed_output is None", "generated": 0}

    duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)

    created: list[int] = []
    if save:
        for ins in bundle.insights:
            row = AIInsight(
                business_date=today,
                title=ins.title,
                observation=ins.observation,
                confidence=ins.confidence,
                urgency=ins.urgency,
                evidence_json=ins.evidence,
                suggested_action=ins.suggested_action,
                sources_used=ins.sources_used or sources,
                model=model_id,
                status="new",
            )
            db.add(row)
            db.flush()
            created.append(row.id)
        db.commit()

    # Usage info for cost tracking
    usage = getattr(response, "usage", None)
    usage_dict = {}
    if usage is not None:
        usage_dict = {
            "input_tokens": getattr(usage, "input_tokens", 0),
            "output_tokens": getattr(usage, "output_tokens", 0),
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0),
            "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0),
        }

    return {
        "ok": True,
        "business_date": today.isoformat(),
        "generated": len(bundle.insights),
        "created_ids": created,
        "model": model_id,
        "duration_ms": duration_ms,
        "context_chars": len(context),
        "sources_included": sources,
        "usage": usage_dict,
    }
