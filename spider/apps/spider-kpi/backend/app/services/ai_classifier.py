"""AI classification layer for Slack + ClickUp signals.

Takes an ``IssueSignal`` that already matched a rule-based pattern and asks
Claude Haiku to:

  * Confirm whether the signal is a **real issue** vs **team chatter**.
  * Generate a clean natural-language **title** + **summary** for DECI drafts.
  * Suggest a **department** and a **refined severity**.

Design choices:
  * ``claude-haiku-4-5`` — cost-efficient (≈$0.001 per signal at Spider Grills
    volume, ~$1/day ceiling). Classification is exactly the "simple, speed-
    critical" niche Haiku is built for.
  * ``client.messages.parse()`` with a Pydantic response model — guarantees
    valid JSON output, no manual parsing, no schema drift.
  * **Fail-silent**: any missing key, network error, timeout, or validation
    failure returns ``None`` and the caller keeps the rule-based metadata.
    The AI layer can never break the ingestion pipeline.
  * **Only called after rule-based match** — we don't ask Claude about every
    message, only about the ~50-200/day that already passed the keyword scan.
"""
from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.core.config import get_settings


logger = logging.getLogger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# Output schema — what the classifier returns
# ---------------------------------------------------------------------------

Classification = Literal[
    "real_issue",          # genuine problem needing tracking/resolution
    "team_chatter",        # team discussion, no action needed
    "decision_made",       # a decision was reached that should be logged
    "question_pending",    # unanswered question that may need escalation
    "escalation_needed",   # urgent, needs immediate attention
    "not_applicable",      # matched a pattern but isn't a real signal
]

Severity = Literal["critical", "warning", "info"]

Department = Literal[
    "Product/Engineering",
    "Customer Experience",
    "Marketing",
    "Operations",
    "Finance",
    "GA",
]


class AIClassification(BaseModel):
    """Structured output the classifier returns."""

    classification: Classification = Field(
        description="What kind of signal this is."
    )
    severity: Severity = Field(
        description="Refined severity tier after reading the message in context."
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence that the classification is correct (0.0-1.0)."
    )
    title: str = Field(
        max_length=120,
        description="Clean one-line title for a DECI draft (no quoting, no ellipses).",
    )
    summary: str = Field(
        max_length=280,
        description="One or two sentence plain-English summary of what's happening.",
    )
    suggested_department: Optional[Department] = Field(
        default=None,
        description="Which division should own this if a DECI draft is created.",
    )
    is_draft_worthy: bool = Field(
        description=(
            "True if this deserves a DECI draft (real_issue, escalation_needed, "
            "or high-signal decision_made). False for chatter / questions / NA."
        ),
    )


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are the signal-classification layer of the Spider Grills KPI dashboard.

Spider Grills makes the Venom grill temperature controller, plus the Huntsman and Giant Huntsman grills. They sell on Shopify, support customers via Freshdesk, track internal work in ClickUp, and communicate in Slack. The team is small — every open decision matters.

You receive signals that were already flagged by a keyword-matching rule (e.g. a Slack message mentioned "broken" or "crash", or a ClickUp task is urgent priority). Your job is to read the actual text and decide whether the rule was right — is this a real issue, team chatter, a decision that needs logging, or noise?

Output a classification with these fields:

- **classification** — one of:
  - `real_issue`: genuine problem needing tracking (Venom fault, customer complaint, refund request, firmware regression, etc.)
  - `escalation_needed`: urgent, critical, needs immediate attention (multiple customers, blocking, safety, revenue impact)
  - `decision_made`: a consequential decision was reached in the message that should be logged to DECI
  - `question_pending`: important unanswered question likely to need follow-up
  - `team_chatter`: normal team discussion, banter, acknowledgment, thanks — no action
  - `not_applicable`: rule matched but the signal isn't actually what it looked like (false positive)

- **severity** — `critical` (drop-everything / customer-facing / revenue), `warning` (needs attention this week), `info` (worth noting, not urgent)

- **confidence** — 0.0-1.0, how sure you are of the classification

- **title** — ≤120 chars, clean one-line title suitable for a DECI decision. No quote marks, no ellipses, no "[AUTOMATED]" prefixes, no emoji. Write it like a product manager would.

- **summary** — 1-2 sentences, plain English, describes what's happening and why it matters. Not a restatement of the raw text.

- **suggested_department** — which Spider Grills division owns this:
  - `Product/Engineering` — firmware, hardware, device faults, telemetry, cook failures, Venom/Huntsman issues
  - `Customer Experience` — support, complaints, refunds, returns, CSAT, ticket volume
  - `Marketing` — campaigns, content, ads, website, brand, ambassadors
  - `Operations` — inventory, fulfillment, shipping, warehouse, wholesale/retail, vendor ops
  - `Finance` — pricing, cost, margin, cash flow
  - `GA` — general admin, HR, legal, policy

- **is_draft_worthy** — true ONLY if this deserves a DECI draft. `real_issue` and `escalation_needed` are usually draft-worthy. `decision_made` sometimes. `team_chatter`, `question_pending`, and `not_applicable` are almost never. Be selective — the goal is signal, not noise.

Be decisive and terse. Don't hedge. If the rule was wrong, say so via `classification: not_applicable` with low confidence — the team needs you to cut noise, not justify it.
"""


def _build_user_content(signal_dict: dict[str, Any]) -> str:
    """Serialize a signal into a compact, model-friendly prompt."""
    source = signal_dict.get("source") or "unknown"
    pattern = signal_dict.get("signal_type") or "unknown"
    meta = signal_dict.get("metadata_json") or {}
    lines = [
        f"Source: {source}",
        f"Rule-based pattern: {pattern}",
        f"Rule-based severity: {signal_dict.get('severity') or 'unknown'}",
    ]

    if source == "slack":
        ch = meta.get("channel_id")
        if ch:
            lines.append(f"Slack channel: #{ch}")
        if meta.get("thread_ts"):
            lines.append(f"(part of a thread)")
    elif source == "clickup":
        lines.append(f"ClickUp list: {meta.get('list_name') or '—'}")
        lines.append(f"ClickUp space: {meta.get('space_name') or '—'}")
        lines.append(f"Priority: {meta.get('priority') or 'unset'}")
        lines.append(f"Status: {meta.get('status') or 'unset'}")

    text = signal_dict.get("summary") or signal_dict.get("title") or ""
    lines.append("")
    lines.append("Message / task text:")
    lines.append("-----")
    lines.append(text[:2000])  # cap input length
    lines.append("-----")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_configured() -> bool:
    return bool(settings.anthropic_api_key)


def classify_signal(signal_dict: dict[str, Any]) -> Optional[AIClassification]:
    """Classify a single rule-matched signal. Returns None on any failure.

    ``signal_dict`` is a plain dict (not the SQLAlchemy row) so this function
    can be called safely outside a session context. Expected keys: ``source``,
    ``signal_type``, ``severity``, ``title``, ``summary``, ``metadata_json``.
    """
    if not is_configured():
        return None

    try:
        # Lazy import so the module loads even if anthropic isn't installed yet.
        import anthropic
    except ImportError:
        logger.info("anthropic package not installed — skipping AI classification")
        return None

    try:
        client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.anthropic_classifier_timeout_seconds,
            max_retries=1,  # Don't burn budget retrying; fail-silent if Claude is down.
        )
        user_content = _build_user_content(signal_dict)
        response = client.messages.parse(
            model=settings.anthropic_classifier_model,
            max_tokens=settings.anthropic_classifier_max_tokens,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                # Cache the system prompt so Haiku's cache_read price applies
                # when we classify the 2nd+ signal in a sync. Minimum prefix
                # for Haiku is 4096 tokens — our prompt + tool schema clears
                # this comfortably on first full sync.
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_content}],
            output_format=AIClassification,
        )
        parsed = response.parsed_output
        if parsed is None:
            logger.warning("AI classifier: parsed_output is None for signal %s", signal_dict.get("signal_type"))
            return None
        return parsed
    except Exception as exc:
        # Swallow everything — the rule-based pipeline continues unchanged.
        logger.warning("AI classifier failed (non-fatal): %s", exc)
        return None


def classification_to_metadata(c: AIClassification) -> dict[str, Any]:
    """Serialize to a dict for storage under ``signal.metadata_json['ai']``."""
    return {
        "classification": c.classification,
        "severity": c.severity,
        "confidence": round(c.confidence, 3),
        "title": c.title,
        "summary": c.summary,
        "suggested_department": c.suggested_department,
        "is_draft_worthy": c.is_draft_worthy,
        "model": settings.anthropic_classifier_model,
    }
