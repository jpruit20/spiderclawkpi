"""Weekly self-grade: Opus reads the last 7d of AI-generated artifacts,
the reactions they got from the team, and any downstream outcomes, then
writes a structured evaluation of its own performance plus a
``prompt_delta`` suggesting how to improve the insight-engine system
prompt.

The delta is never auto-applied. Joseph has to approve each one via the
UI — otherwise Opus is grading its own work and rewriting its own
prompt in a tight loop that can drift unsupervised.

Runs Sunday 10:00 ET (between the daily insight pass and the Monday
morning brief) so any approved delta is live for the new week.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    AIFeedback,
    AIInsight,
    AISelfGrade,
    DeciDecision,
    FirmwareRelease,
    FreshdeskTicket,
    IssueSignal,
)


logger = logging.getLogger(__name__)
settings = get_settings()


# ── structured output schema ────────────────────────────────────────────


class SourceGrade(BaseModel):
    source: Literal["ai_insight", "deci_draft", "issue_signal", "firmware_verdict"]
    grade: Literal["A", "B", "C", "D", "F"] = Field(..., description="A=excellent, F=broken")
    precision_note: str = Field(max_length=400, description="1-2 sentences on precision + specific miss patterns")
    specific_wins: list[str] = Field(default_factory=list, description="Up to 3 artifacts that worked well, cited by id or title")
    specific_misses: list[str] = Field(default_factory=list, description="Up to 3 artifacts that missed, cited by id or title + why")


class RejectionTheme(BaseModel):
    theme: str = Field(max_length=120, description="Short label for a recurring kind of miss")
    frequency: int = Field(ge=1, description="How many rejections fit this theme")
    example: str = Field(max_length=240, description="One concrete example from the data")


class SelfGradeReport(BaseModel):
    overall_summary: str = Field(max_length=800, description="2-3 sentences on how the AI layer performed this week")
    source_grades: list[SourceGrade]
    rejection_themes: list[RejectionTheme] = Field(default_factory=list, max_length=6)
    prompt_delta: Optional[str] = Field(
        None,
        max_length=1200,
        description=(
            "Optional concrete text to append to the insight engine's system prompt to address the patterns "
            "observed. Should be a tight rule (not a paragraph of caveats). Return null if nothing actionable."
        ),
    )


# ── context builder ─────────────────────────────────────────────────────


def _build_context(db: Session, *, window_days: int = 7) -> tuple[str, int, int]:
    """Assemble artifact + feedback digest for Opus. Returns
    (context_string, artifacts_scored, feedback_count)."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)

    # --- AI insights with any attached feedback
    insights = db.execute(
        select(AIInsight).where(AIInsight.business_date >= cutoff.date())
        .order_by(desc(AIInsight.business_date))
    ).scalars().all()

    # --- DECI drafts created in window
    drafts = db.execute(
        select(DeciDecision)
        .where(DeciDecision.status == "draft")
        .where(DeciDecision.created_at >= cutoff)
    ).scalars().all()

    # --- Issue signals (AI-classified) in window
    signals = db.execute(
        select(IssueSignal)
        .where(IssueSignal.created_at >= cutoff)
        .order_by(desc(IssueSignal.created_at))
        .limit(120)
    ).scalars().all()

    # --- Firmware verdicts touched in window
    releases = db.execute(
        select(FirmwareRelease)
        .where(FirmwareRelease.updated_at >= cutoff)
        .order_by(desc(FirmwareRelease.updated_at))
        .limit(12)
    ).scalars().all()

    # --- All feedback in window
    feedback_rows = db.execute(
        select(AIFeedback).where(AIFeedback.updated_at >= cutoff)
    ).scalars().all()

    # Key feedback by (artifact_type, artifact_id)
    fb_by_key: dict[tuple[str, str], list[AIFeedback]] = defaultdict(list)
    for fb in feedback_rows:
        fb_by_key[(fb.artifact_type, fb.artifact_id)].append(fb)

    # --- Outcome signal: tickets resolved in window (proxy for CX impact)
    tickets_resolved = db.execute(
        select(func.count(FreshdeskTicket.id))
        .where(FreshdeskTicket.status.in_(["resolved", "closed"]))
        .where(FreshdeskTicket.updated_at_source >= cutoff)
    ).scalar() or 0

    lines: list[str] = []
    lines.append(f"=== AI LAYER SELF-GRADE CONTEXT — {now.isoformat()} ===")
    lines.append(f"Window: last {window_days}d. Tickets resolved in window: {tickets_resolved}.")
    lines.append("")
    lines.append(
        "Below are every AI-generated artifact in the window and the reactions the team gave them. "
        "Reactions: acted_on (took action), already_knew (true but obvious), wrong (false positive), ignore (not relevant). "
        "Your job is to grade each source, identify recurring failure patterns, and propose at most ONE concrete "
        "prompt_delta if the failure patterns suggest a rule the insight engine should follow."
    )
    lines.append("")

    def _render_feedback(reactions: list[AIFeedback]) -> str:
        if not reactions:
            return "(no feedback yet)"
        parts = []
        c: Counter = Counter(r.reaction for r in reactions)
        parts.append(", ".join(f"{k}={v}" for k, v in c.most_common()))
        notes = [r.note for r in reactions if r.note]
        if notes:
            parts.append("notes: " + " | ".join(n[:120] for n in notes[:3]))
        return "; ".join(parts)

    # Render AI insights
    lines.append(f"## AI INSIGHTS ({len(insights)})")
    for ins in insights:
        reactions = fb_by_key.get(("ai_insight", str(ins.id)), [])
        lines.append(f"  - id={ins.id} [{ins.urgency}] \"{ins.title}\"")
        lines.append(f"      observation: {(ins.observation or '')[:240]}")
        if ins.suggested_action:
            lines.append(f"      action: {ins.suggested_action[:160]}")
        lines.append(f"      feedback: {_render_feedback(reactions)}")
    lines.append("")

    # DECI drafts
    lines.append(f"## DECI DRAFTS ({len(drafts)})")
    for d in drafts[:50]:
        reactions = fb_by_key.get(("deci_draft", str(d.id)), [])
        title = (d.title or "(untitled)")[:140]
        lines.append(f"  - id={d.id} [{d.status}] \"{title}\"")
        lines.append(f"      feedback: {_render_feedback(reactions)}")
    lines.append("")

    # Issue signals
    lines.append(f"## ISSUE SIGNALS ({len(signals)})")
    for s in signals[:50]:
        reactions = fb_by_key.get(("issue_signal", str(s.id)), [])
        meta = s.metadata_json if isinstance(s.metadata_json, dict) else {}
        ai_meta = meta.get("ai") if isinstance(meta, dict) else None
        classification = None
        ai_title = None
        if isinstance(ai_meta, dict):
            classification = ai_meta.get("classification")
            ai_title = ai_meta.get("title")
        label = ai_title or s.title or "(no title)"
        lines.append(
            f"  - id={s.id} [{s.source}/{s.signal_type}/{s.severity or '?'}/{classification or '?'}] \"{label[:140]}\""
        )
        lines.append(f"      feedback: {_render_feedback(reactions)}")
    lines.append("")

    # Firmware verdicts
    lines.append(f"## FIRMWARE VERDICTS ({len(releases)})")
    for r in releases:
        reactions = fb_by_key.get(("firmware_verdict", str(r.id)), [])
        report = r.beta_report_json or {}
        tally = report.get("tally") or {}
        health = report.get("release_health")
        lines.append(
            f"  - id={r.id} version={r.version} status={r.status} "
            f"health={health or '?'} tally={json.dumps(tally)[:160]}"
        )
        lines.append(f"      feedback: {_render_feedback(reactions)}")
    lines.append("")

    lines.append("=== END CONTEXT ===")

    artifacts_scored = len(insights) + len(drafts) + len(signals) + len(releases)
    return "\n".join(lines), artifacts_scored, len(feedback_rows)


# ── prompt ──────────────────────────────────────────────────────────────


SYSTEM_PROMPT = """You are a meta-evaluator for the Spider Grills KPI dashboard's AI layer.

Every week you receive a digest of every AI-generated artifact from the past 7 days — cross-source insights, auto-drafted DECI decisions, AI-classified Slack/ClickUp signals, and firmware beta verdicts — along with the reactions the team gave each one (acted_on, already_knew, wrong, ignore).

Your job:
1. Grade each source (A-F) on whether it produced actionable value this week.
2. Identify recurring themes in rejections: what kinds of artifacts keep getting marked `wrong` or `already_knew`? These are cheap wins for improvement.
3. Propose at most ONE concrete `prompt_delta` — a short rule to append to the insight engine's system prompt — that would prevent this week's worst miss pattern from recurring. If nothing actionable emerges, return null.

Rules for prompt_delta:
- It must be a tight, enforceable rule the model can follow. Not "be more careful" — instead "do not flag WoW revenue drops unless the seasonal percentile rank also dropped by ≥10 points."
- It must be grounded in ≥3 specific `wrong` or `already_knew` reactions in this week's data.
- If a rule would contradict an existing good behavior (too many `acted_on` reactions on the same pattern), skip it.
- Tone: terse, imperative, fits in one paragraph. No hedging.

Feedback interpretation:
- `acted_on` = full credit, the insight produced real work
- `already_knew` = true but adds no value; worth flagging if a source produces many of these
- `wrong` = false positive; costly because it erodes trust
- `ignore` = neutral; one-off skip, not a signal unless clustered

Be honest. A source with 2 `wrong` out of 3 artifacts gets a D. A source with high `acted_on` gets an A even if total volume is low.
"""


# ── public entry point ──────────────────────────────────────────────────


def is_configured() -> bool:
    return bool(settings.anthropic_api_key)


def run_weekly_self_grade(db: Session, *, window_days: int = 7) -> dict[str, Any]:
    """Build context → call Opus → persist AISelfGrade row. Returns a
    summary dict. Fails silently if ANTHROPIC_API_KEY is missing."""
    if not is_configured():
        return {"ok": False, "reason": "ANTHROPIC_API_KEY not configured"}

    try:
        import anthropic
    except ImportError:
        return {"ok": False, "reason": "anthropic package not installed"}

    context, artifacts_scored, feedback_count = _build_context(db, window_days=window_days)

    if feedback_count == 0 and artifacts_scored == 0:
        return {"ok": True, "reason": "no_data_in_window", "artifacts_scored": 0, "feedback_count": 0}

    started = datetime.now(timezone.utc)
    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        timeout=300,
        max_retries=1,
    )

    model_id = "claude-opus-4-7"
    try:
        response = client.messages.parse(
            model=model_id,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": context}],
            output_format=SelfGradeReport,
        )
    except Exception as exc:
        logger.exception("Opus self-grade call failed")
        return {"ok": False, "reason": f"api_error: {exc}"}

    report: Optional[SelfGradeReport] = response.parsed_output
    if report is None:
        return {"ok": False, "reason": "parsed_output is None"}

    duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)

    precision_by_source = {
        sg.source: {"grade": sg.grade, "precision_note": sg.precision_note,
                    "specific_wins": sg.specific_wins, "specific_misses": sg.specific_misses}
        for sg in report.source_grades
    }
    rejection_themes_json = [t.model_dump() for t in report.rejection_themes]

    usage = getattr(response, "usage", None)
    usage_dict = {}
    if usage is not None:
        usage_dict = {
            "input_tokens": getattr(usage, "input_tokens", 0),
            "output_tokens": getattr(usage, "output_tokens", 0),
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0),
            "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0),
        }

    row = AISelfGrade(
        run_at=datetime.now(timezone.utc),
        window_days=window_days,
        model=model_id,
        artifacts_scored=artifacts_scored,
        feedback_count=feedback_count,
        precision_by_source=precision_by_source,
        rejection_themes=rejection_themes_json,
        overall_summary=report.overall_summary,
        prompt_delta=report.prompt_delta,
        duration_ms=duration_ms,
        usage_json=usage_dict,
    )
    db.add(row)
    db.commit()

    return {
        "ok": True,
        "id": row.id,
        "artifacts_scored": artifacts_scored,
        "feedback_count": feedback_count,
        "has_prompt_delta": bool(row.prompt_delta),
        "duration_ms": duration_ms,
        "model": model_id,
    }
