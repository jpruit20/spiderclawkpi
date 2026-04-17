"""DECI auto-draft engine.

Reads recent ``IssueSignal`` rows (from Slack, ClickUp, or any other source)
and either:

  1. **Appends a `DeciDecisionLog`** to an already-open DECI decision that
     matches the signal's ``(origin_signal_type, origin_context_key)`` —
     consolidating activity around the same issue over time.
  2. **Creates a new `DeciDecision` draft** (``status='draft'``) with the
     provenance columns populated so the next matching signal updates this
     same decision.

Runs at the tail of every Slack and ClickUp sync, and via the scheduler.
Rules-based today; LLM-driven classification is a clean phase-3 layer on
top (same inputs/outputs).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models import (
    DeciDecision,
    DeciDecisionLog,
    IssueSignal,
    SlackChannel,
    ClickUpTask,
)


logger = logging.getLogger(__name__)

AUTO_DRAFT_AUTHOR = "system:autodraft"
DRAFT_STATUS = "draft"
DISMISSED_STATUS = "dismissed"

# Decision statuses we consider "still open and mergeable" — new signals update
# these instead of spawning a new draft. Draft is included on purpose so a
# later signal of the same kind appends a log to the existing draft rather
# than making a duplicate.
OPEN_STATUSES = {
    "draft",
    "not_started",
    "in_progress",
    "blocked",
}

# Severity → DECI priority mapping.
SEVERITY_TO_PRIORITY = {
    "critical": "critical",
    "high": "high",
    "warning": "medium",
    "medium": "medium",
    "info": "low",
    "low": "low",
}

# Signal-type-specific title prefixes + department hints.
TITLE_PREFIX = {
    "slack.urgent_ping": "Urgent Slack ping",
    "slack.venom_fault": "Venom fault reported",
    "slack.crash": "System/device crash reported",
    "slack.broken": "Something reported broken",
    "slack.refund_request": "Refund / chargeback mentioned",
    "slack.error_word": "Error discussed",
    "slack.firmware_concern": "Firmware concern raised",
    "slack.customer_complaint": "Customer complaint surfaced",
    "slack.help_request": "Help requested",
    "clickup.urgent_priority": "Urgent ClickUp task opened",
    "clickup.venom_fault": "ClickUp: Venom fault",
    "clickup.crash": "ClickUp: crash/hang",
    "clickup.broken": "ClickUp: something broken",
    "clickup.refund_request": "ClickUp: refund/chargeback",
    "clickup.error_word": "ClickUp: error reported",
    "clickup.firmware_concern": "ClickUp: firmware concern",
    "clickup.customer_complaint": "ClickUp: customer complaint",
    "clickup.urgent_ping": "ClickUp: urgent flagged",
}


# Which signal types are important enough to auto-draft a decision for.
# Keep this tight initially — expand once Joseph sees what lands.
AUTO_DRAFT_SIGNAL_TYPES: frozenset[str] = frozenset({
    "slack.venom_fault",
    "slack.crash",
    "slack.urgent_ping",
    "slack.refund_request",
    "slack.customer_complaint",
    "slack.firmware_concern",
    "clickup.urgent_priority",
    "clickup.venom_fault",
    "clickup.crash",
    "clickup.refund_request",
    "clickup.customer_complaint",
    "clickup.firmware_concern",
})


def _context_key_for_signal(signal: IssueSignal) -> Optional[str]:
    """Derive a stable context key so repeated signals of the same type in the
    same place consolidate. Slack: channel_id. ClickUp: list_id (falls back to
    space_id). Unknown source: None → no consolidation.
    """
    meta = signal.metadata_json or {}
    if signal.source == "slack":
        ch = meta.get("channel_id")
        return f"slack:channel:{ch}" if ch else None
    if signal.source == "clickup":
        lst = meta.get("list_id")
        space = meta.get("space_id")
        if lst:
            return f"clickup:list:{lst}"
        if space:
            return f"clickup:space:{space}"
        return None
    return None


def _department_hint(signal: IssueSignal, db: Session) -> Optional[str]:
    """Best-effort mapping from a signal's origin channel/list → DECI department.
    Returns None if we can't guess — Joseph picks on review.
    """
    meta = signal.metadata_json or {}
    if signal.source == "slack":
        channel_id = meta.get("channel_id")
        if channel_id:
            ch = db.execute(select(SlackChannel).where(SlackChannel.channel_id == channel_id)).scalars().first()
            name = (ch.name or "").lower() if ch else ""
            if not name:
                return None
            if "product" in name or "firmware" in name or "dev" in name:
                return "Product / Engineering"
            if "customer" in name or "support" in name or "cx" in name:
                return "Customer Experience"
            if "marketing" in name or "content" in name or "campaign" in name:
                return "Marketing"
            if "inventory" in name or "warehouse" in name or "ops" in name or "wholesale" in name or "retail" in name:
                return "Operations"
            return None
    if signal.source == "clickup":
        space_name = (meta.get("space_name") or "").lower()
        if "product" in space_name:
            return "Product / Engineering"
        if "marketing" in space_name:
            return "Marketing"
        return None
    return None


def _render_title(signal: IssueSignal) -> str:
    prefix = TITLE_PREFIX.get(signal.signal_type, f"Auto-detected: {signal.signal_type}")
    summary = (signal.title or signal.summary or "")[:80].strip()
    if summary:
        return f"{prefix}: {summary}"[:250]
    return prefix[:250]


def _render_description(signal: IssueSignal) -> str:
    meta = signal.metadata_json or {}
    lines = [signal.summary or ""]
    lines.append("")
    lines.append(f"Source: {signal.source}")
    lines.append(f"Signal: {signal.signal_type}  (severity: {signal.severity})")
    if signal.source == "slack":
        if meta.get("channel_id"):
            lines.append(f"Channel: {meta.get('channel_id')}")
        if meta.get("message_ts"):
            lines.append(f"Message ts: {meta.get('message_ts')}")
        if meta.get("thread_ts"):
            lines.append(f"Thread ts: {meta.get('thread_ts')}")
    elif signal.source == "clickup":
        if meta.get("url"):
            lines.append(f"Task URL: {meta.get('url')}")
        if meta.get("list_name"):
            lines.append(f"List: {meta.get('list_name')}")
        if meta.get("status"):
            lines.append(f"ClickUp status: {meta.get('status')}")
        if meta.get("priority"):
            lines.append(f"ClickUp priority: {meta.get('priority')}")
    lines.append("")
    lines.append("_Auto-drafted by KPI dashboard from upstream activity._")
    lines.append("_Promote this draft to a real decision once you've reviewed, or dismiss if not actionable._")
    return "\n".join(lines)


def _render_log_text(signal: IssueSignal) -> str:
    meta = signal.metadata_json or {}
    snippet = (signal.summary or signal.title or "")[:200]
    location = ""
    if signal.source == "slack" and meta.get("channel_id"):
        location = f"Slack channel {meta['channel_id']}"
    elif signal.source == "clickup" and meta.get("url"):
        location = f"ClickUp {meta.get('list_name') or ''} — {meta['url']}"
    prefix = f"[{signal.severity}] {signal.signal_type}"
    return f"{prefix} ({location}): {snippet}"


def process_signal(db: Session, signal: IssueSignal) -> tuple[str, Optional[str]]:
    """Either update an open matching decision or create a new draft.

    Returns ``(action, decision_id)`` where action is one of
    ``'appended_log'``, ``'created_draft'``, ``'skipped'``.
    """
    if signal.signal_type not in AUTO_DRAFT_SIGNAL_TYPES:
        return "skipped", None

    context_key = _context_key_for_signal(signal)
    if context_key is None:
        return "skipped", None

    # Find open decision with same origin.
    existing = db.execute(
        select(DeciDecision).where(
            and_(
                DeciDecision.origin_signal_type == signal.signal_type,
                DeciDecision.origin_context_key == context_key,
                DeciDecision.status.in_(list(OPEN_STATUSES)),
            )
        ).order_by(DeciDecision.created_at.desc()).limit(1)
    ).scalars().first()

    if existing is not None:
        # Dedup: don't add the same log twice. Use decision_text equality.
        log_text = _render_log_text(signal)
        already = db.execute(select(DeciDecisionLog).where(
            DeciDecisionLog.decision_id == existing.id,
            DeciDecisionLog.decision_text == log_text,
        ).limit(1)).scalars().first()
        if already is not None:
            return "skipped", existing.id
        db.add(DeciDecisionLog(
            decision_id=existing.id,
            decision_text=log_text,
            made_by=AUTO_DRAFT_AUTHOR,
            notes=None,
        ))
        return "appended_log", existing.id

    # Create a new draft.
    import uuid
    did = str(uuid.uuid4())
    priority = SEVERITY_TO_PRIORITY.get((signal.severity or "").lower(), "medium")
    dept = _department_hint(signal, db)
    now = datetime.now(timezone.utc)
    decision = DeciDecision(
        id=did,
        title=_render_title(signal),
        description=_render_description(signal),
        type="Issue",
        status=DRAFT_STATUS,
        priority=priority,
        department=dept,
        created_by=AUTO_DRAFT_AUTHOR,
        cross_functional=False,
        origin_signal_type=signal.signal_type,
        origin_context_key=context_key,
        auto_drafted_at=now,
    )
    db.add(decision)
    db.add(DeciDecisionLog(
        decision_id=did,
        decision_text=_render_log_text(signal),
        made_by=AUTO_DRAFT_AUTHOR,
        notes=f"Auto-drafted from {signal.source} signal id={signal.id}",
    ))
    return "created_draft", did


def autodraft_from_signals(db: Session, since: datetime | None = None) -> dict[str, int]:
    """Walk recent IssueSignal rows and route each into the auto-draft engine.

    Idempotent — an already-processed signal either matches an existing
    decision (log dedupe short-circuits) or would reopen a dismissed/resolved
    decision only if the user's review hasn't made it so that a NEW draft is
    warranted, which is the intended behavior.
    """
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(days=14)

    signals = db.execute(
        select(IssueSignal).where(IssueSignal.created_at >= since).order_by(IssueSignal.created_at)
    ).scalars().all()

    counts = {"processed": 0, "created_drafts": 0, "appended_logs": 0, "skipped": 0}
    for s in signals:
        counts["processed"] += 1
        try:
            action, _ = process_signal(db, s)
            if action == "created_draft":
                counts["created_drafts"] += 1
            elif action == "appended_log":
                counts["appended_logs"] += 1
            else:
                counts["skipped"] += 1
        except Exception:
            logger.exception("autodraft failed on signal id=%s", s.id)

    db.flush()
    return counts
