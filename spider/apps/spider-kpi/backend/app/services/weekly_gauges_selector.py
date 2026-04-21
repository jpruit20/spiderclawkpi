"""Weekly Opus 4.7 pass that picks the 8 Command Center priority gauges.

Runs Monday mornings. Given the metric catalog, recent business
context (last 4 weeks of KPIs, open DECI decisions, critical signals,
recent incidents), Opus returns 8 gauges with rationale. The selection
is persisted to ``weekly_gauge_selection`` and served back to the UI.

Values themselves are resolved live in
``weekly_gauges_catalog.resolve_metric`` — this service only picks
*which* metrics to show this week.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import anthropic
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    AIInsight,
    DeciDecision,
    IssueSignal,
    KPIDaily,
    Recommendation,
    WeeklyGaugeSelection,
)
from app.services.weekly_gauges_catalog import CATALOG, list_catalog_for_prompt


logger = logging.getLogger(__name__)


GAUGE_COUNT = 5

# Anchor gauges — permanently shown at the top of the Command Center
# hero (revenue primary + fleet/success flanking). Opus MUST NOT pick
# these, because they're always visible; picking them would waste a
# curated slot on a metric we're already showing as fixed anchors.
ANCHOR_KEYS: tuple[str, ...] = (
    "revenue_7d",
    "fleet_active_now",
    "cook_success_rate_7d",
)


class GaugePick(BaseModel):
    metric_key: str = Field(description="Must be one of the catalog keys provided.")
    rationale: str = Field(description="1-2 sentences on why THIS metric matters this specific week. Reference current context.")
    target_value: Optional[float] = Field(default=None, description="Optional numeric target. Use when there's a clear goal.")
    healthy_band_low: Optional[float] = Field(default=None, description="Lower bound of the 'green' zone for this metric (in its native units).")
    healthy_band_high: Optional[float] = Field(default=None, description="Upper bound of the 'green' zone.")
    gauge_style: str = Field(default="radial", description="'radial' | 'bar' | 'spark'. Pick the shape that reads best at a glance.")


class WeeklyPickBundle(BaseModel):
    gauges: list[GaugePick] = Field(description=f"Exactly {GAUGE_COUNT} gauges, ordered by importance (rank 1 is most important).")
    overall_theme: str = Field(description="One sentence capturing what the selection is collectively watching for this week.")


SYSTEM_PROMPT = """You are the Chief of Staff for Spider Grills, a premium
BBQ-controller company building the Venom smart pellet-grill brain.
Thousands of Venom controllers are in the field; the company sells
through Shopify, runs paid media on Meta/Google/TikTok via TripleWhale,
and handles customer support in Freshdesk.

Your job every Monday: pick the 5 most-important *curated* gauges for
the company's Command Center dashboard top strip. The selection is shown
for the coming week. Same 5 gauges stay up all week; their values update
live. You are curating *what leadership needs to see this week*, not a
generic KPI set.

There are also 3 ANCHOR gauges permanently shown at the top of the
Command Center — revenue, fleet active, cook success. Do NOT include
these in your 5 picks. Their keys are listed in the user message and
are already covered visually — picking them again wastes a slot. Pick
metrics that complement the anchors, not duplicate them.

How to pick:
1. Read the current business context (past 4 weeks of KPIs, open DECI
   decisions, recent critical signals, recent AI insights).
2. From the catalog of measurable metrics, pick the 8 that will most
   obviously change the right/wrong decision this week.
3. Lean toward variety across categories (commerce, marketing, cx,
   fleet, ops, engineering) — but don't force coverage if the week is
   genuinely about one or two themes.
4. Prefer metrics tied to *active* DECI decisions or *recent* incidents
   over generic ones.
5. For each gauge, write a 1-2 sentence rationale that cites the *specific*
   context you're watching. Bad: "Revenue matters." Good: "Inventory of
   the 22in Kettle Cart ran low on 2026-04-18; revenue-per-session is
   the cleanest signal of whether the replenishment lands in time."
6. Set healthy_band + target numerically when there's a clear threshold
   (MER > 2.0, CSAT > 90, first-response < 4h). Leave them null when
   the metric is directional without a fixed goal.
7. Rank matters. rank 1 is the highest-stakes gauge for this week —
   what the CEO should look at first.

Return ONLY the structured output. No extra commentary."""


def _iso_week_start(d: date) -> date:
    """Monday of the ISO week containing ``d``."""
    return d - timedelta(days=d.weekday())


def _build_context(db: Session) -> str:
    """Assemble the business context Opus sees when picking gauges.

    Kept under ~15k tokens so we can prompt-cache the system prompt
    and stay well inside Opus's 1M window.
    """
    today = date.today()
    four_weeks_ago = today - timedelta(days=28)

    # Last 28 days of KPIs
    kpi_rows = db.execute(
        select(KPIDaily).where(KPIDaily.business_date >= four_weeks_ago)
        .order_by(KPIDaily.business_date)
    ).scalars().all()
    kpi_compact = [
        {
            "date": r.business_date.isoformat(),
            "revenue": float(r.revenue or 0),
            "orders": int(r.orders or 0),
            "aov": float(r.average_order_value or 0),
            "sessions": int(r.sessions or 0),
            "cvr_pct": float(r.conversion_rate or 0),
            "ad_spend": float(r.ad_spend or 0),
            "mer": float(r.mer or 0),
            "tickets": int(r.tickets_created or 0),
            "backlog": int(r.open_backlog or 0),
            "first_resp_h": float(r.first_response_time or 0),
            "csat": float(r.csat or 0),
        }
        for r in kpi_rows
    ]

    # Active / recently-opened DECI decisions
    deci_rows = db.execute(
        select(DeciDecision)
        .where(DeciDecision.status != "archived")
        .order_by(desc(DeciDecision.updated_at))
        .limit(20)
    ).scalars().all()
    deci_compact = [
        {
            "id": d.id,
            "title": d.title,
            "status": d.status,
            "department": d.department,
            "priority": d.priority,
            "due_date": d.due_date.isoformat() if d.due_date else None,
        }
        for d in deci_rows
    ]

    # Recent critical signals (last 14d)
    signal_cutoff = date.today() - timedelta(days=14)
    signal_rows = db.execute(
        select(IssueSignal)
        .where(IssueSignal.business_date >= signal_cutoff)
        .order_by(desc(IssueSignal.business_date))
        .limit(25)
    ).scalars().all()
    signals_compact = [
        {
            "date": s.business_date.isoformat() if s.business_date else None,
            "source": s.source,
            "severity": s.severity,
            "title": (s.title or "")[:120],
        }
        for s in signal_rows
    ]

    # Recent AI insights (last 14d) — what Opus has already flagged as important
    insight_cutoff = date.today() - timedelta(days=14)
    insight_rows = db.execute(
        select(AIInsight)
        .where(AIInsight.business_date >= insight_cutoff)
        .order_by(desc(AIInsight.business_date))
        .limit(20)
    ).scalars().all()
    insights_compact = [
        {
            "date": i.business_date.isoformat() if i.business_date else None,
            "title": i.title,
            "urgency": i.urgency,
            "action": (i.suggested_action or "")[:200],
        }
        for i in insight_rows
    ]

    # Recent recommendations (leadership-facing drafts)
    rec_rows = db.execute(
        select(Recommendation)
        .order_by(desc(Recommendation.created_at)).limit(20)
    ).scalars().all()
    recs_compact = [
        {"title": r.title, "severity": r.severity, "owner": r.owner_team}
        for r in rec_rows
    ]

    context = {
        "today": today.isoformat(),
        "iso_week_start": _iso_week_start(today).isoformat(),
        "catalog": list_catalog_for_prompt(),
        "kpis_last_28d": kpi_compact,
        "active_deci_decisions": deci_compact,
        "critical_signals_last_14d": signals_compact,
        "recent_ai_insights": insights_compact,
        "open_recommendations": recs_compact,
    }
    return json.dumps(context, default=str, indent=None)


def run_weekly_gauge_selection(
    db: Session,
    *,
    week_start: Optional[date] = None,
    force: bool = False,
) -> dict[str, int]:
    """Invoke Opus to pick this week's 8 gauges. Idempotent:
    if a selection for ``week_start`` already exists and ``force`` is
    False, returns the existing row count without calling Opus.

    Pinned rows from the prior week are carried forward — Opus is told
    about them so it can fill the remaining slots intentionally.
    """
    today = date.today()
    target_week = week_start or _iso_week_start(today)

    # Idempotency — skip if we already have this week's picks
    existing = db.execute(
        select(WeeklyGaugeSelection).where(
            WeeklyGaugeSelection.iso_week_start == target_week
        )
    ).scalars().all()
    if existing and not force:
        return {"ok": True, "week_start": target_week.isoformat(), "existing": len(existing), "generated": 0}

    # Pinned gauges from prior week carry forward
    prior_week = target_week - timedelta(days=7)
    pinned = db.execute(
        select(WeeklyGaugeSelection).where(
            WeeklyGaugeSelection.iso_week_start == prior_week,
            WeeklyGaugeSelection.pinned.is_(True),
        )
    ).scalars().all()

    settings = get_settings()
    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        timeout=180,
        max_retries=1,
    )

    context = _build_context(db)
    if pinned:
        pin_note = "\n\nThe user has PINNED the following gauges from prior weeks — include them in your selection verbatim, filling the rest of the slots around them:\n" + json.dumps([
            {"key": p.metric_key, "rationale": p.rationale, "rank": p.rank} for p in pinned
        ])
    else:
        pin_note = ""

    anchor_note = (
        "\n\nANCHOR GAUGES (already permanently shown — do NOT pick these):\n"
        + "\n".join(f"  - {k}" for k in ANCHOR_KEYS)
    )
    user_msg = (
        f"Select {GAUGE_COUNT} Command Center priority gauges for the "
        f"week starting {target_week.isoformat()}. Here is the current "
        f"business context:\n\n{context}{anchor_note}{pin_note}"
    )

    started = datetime.now(timezone.utc)
    try:
        response = client.messages.parse(
            model="claude-opus-4-7",
            max_tokens=16000,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_msg}],
            output_format=WeeklyPickBundle,
        )
    except Exception as exc:
        logger.exception("weekly_gauge_selection Opus call failed")
        return {"ok": False, "week_start": target_week.isoformat(), "error": f"api_error: {exc}", "generated": 0}

    bundle: Optional[WeeklyPickBundle] = response.parsed_output
    if bundle is None:
        return {"ok": False, "week_start": target_week.isoformat(), "error": "parsed_output_none", "generated": 0}

    # Validate keys exist in catalog AND are not anchors (Opus was told
    # not to pick anchors, but defend against the prompt being ignored).
    valid_picks: list[GaugePick] = []
    for pick in bundle.gauges:
        if pick.metric_key in ANCHOR_KEYS:
            logger.warning("Opus picked anchor key %r — dropping (anchors are rendered separately)", pick.metric_key)
            continue
        if pick.metric_key in CATALOG:
            valid_picks.append(pick)
        else:
            logger.warning("Opus picked unknown metric key %r — dropping", pick.metric_key)
    valid_picks = valid_picks[:GAUGE_COUNT]

    if len(valid_picks) < GAUGE_COUNT:
        # Pad with catalog defaults so we always have GAUGE_COUNT picks.
        # Skip anchors — they're rendered separately in the hero.
        used = {p.metric_key for p in valid_picks}
        fallback_order = [
            "mer_7d", "orders_7d", "tickets_created_7d", "csat_7d",
            "first_response_hours_7d", "aov_7d", "conversion_rate_7d", "sessions_7d",
        ]
        for key in fallback_order:
            if len(valid_picks) >= GAUGE_COUNT:
                break
            if key in used or key in ANCHOR_KEYS or key not in CATALOG:
                continue
            valid_picks.append(GaugePick(
                metric_key=key,
                rationale=f"[Fallback] Padded because Opus returned fewer than {GAUGE_COUNT} valid picks.",
            ))

    # Wipe any prior (unpinned) rows for this week; then persist
    if force:
        db.execute(
            WeeklyGaugeSelection.__table__.delete().where(
                WeeklyGaugeSelection.iso_week_start == target_week,
                WeeklyGaugeSelection.pinned.is_(False),
            )
        )

    selected_at = datetime.now(timezone.utc)
    for rank, pick in enumerate(valid_picks[:GAUGE_COUNT], start=1):
        row = WeeklyGaugeSelection(
            iso_week_start=target_week,
            rank=rank,
            metric_key=pick.metric_key,
            rationale=pick.rationale,
            target_value=pick.target_value,
            healthy_band_low=pick.healthy_band_low,
            healthy_band_high=pick.healthy_band_high,
            gauge_style=pick.gauge_style or "radial",
            selected_by="opus-4-7",
            selection_context_json={"overall_theme": bundle.overall_theme},
            selected_at=selected_at,
        )
        db.add(row)
    db.commit()

    duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    logger.info("weekly_gauge_selection wrote %s gauges for %s in %sms", len(valid_picks), target_week, duration_ms)
    return {
        "ok": True,
        "week_start": target_week.isoformat(),
        "generated": len(valid_picks),
        "duration_ms": duration_ms,
        "overall_theme": bundle.overall_theme,
    }
