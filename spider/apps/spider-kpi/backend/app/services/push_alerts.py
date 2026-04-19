"""Push alerts — real-time Slack DMs on critical signals + structured email.

Everything here is **opt-in** (``PUSH_ALERTS_ENABLED=false`` disables the
whole subsystem) and **fail-silent** (any error is logged and swallowed;
the ingestion pipeline continues unaffected).

Dedup + rate limiting both go through the ``notification_sends`` table so
scheduler restarts, webhook replays, and manual sync triggers don't spam.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.email_allowlist import UnauthorizedRecipientError, assert_allowed
from app.models import IssueSignal, NotificationSend, SlackUser


logger = logging.getLogger(__name__)
settings = get_settings()
BUSINESS_TZ = ZoneInfo("America/New_York")
SLACK_API = "https://slack.com/api"


def is_enabled() -> bool:
    return bool(settings.push_alerts_enabled)


def is_quiet_hour(now: Optional[datetime] = None) -> bool:
    """True if the current ET hour is within the configured quiet window."""
    now = now or datetime.now(BUSINESS_TZ)
    hour = now.astimezone(BUSINESS_TZ).hour
    start = settings.push_alerts_quiet_start_hour
    end = settings.push_alerts_quiet_end_hour
    # Quiet window may wrap midnight (e.g. 22 → 7)
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    # wraps midnight: active if hour >= start OR hour < end
    return hour >= start or hour < end


def _already_sent(db: Session, channel: str, subject_type: str, subject_id: str, recipient: str) -> bool:
    return db.execute(
        select(NotificationSend.id).where(
            NotificationSend.channel == channel,
            NotificationSend.subject_type == subject_type,
            NotificationSend.subject_id == subject_id,
            NotificationSend.recipient == recipient,
        ).limit(1)
    ).first() is not None


def _recent_send_count(db: Session, recipient: str, minutes: int = 60) -> int:
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    count = db.execute(
        select(func.count(NotificationSend.id)).where(
            NotificationSend.recipient == recipient,
            NotificationSend.sent_at >= since,
        )
    ).scalar()
    return int(count or 0)


def _record_send(
    db: Session,
    channel: str,
    recipient: str,
    subject_type: str,
    subject_id: Optional[str],
    success: bool,
    error: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    db.add(NotificationSend(
        channel=channel,
        recipient=recipient,
        subject_type=subject_type,
        subject_id=subject_id,
        sent_at=datetime.now(timezone.utc),
        success=success,
        error=error,
        metadata_json=metadata or {},
    ))
    db.flush()


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------

def _slack_user_id_by_email(db: Session, email: str) -> Optional[str]:
    """Look up a Slack user_id by email. Prefers cached SlackUser table;
    falls back to users.lookupByEmail if the local table is empty.
    """
    email = (email or "").strip().lower()
    if not email:
        return None
    row = db.execute(
        select(SlackUser.user_id).where(func.lower(SlackUser.email) == email)
    ).scalar()
    if row:
        return row
    # Fallback: hit Slack API
    if not settings.slack_bot_token:
        return None
    try:
        r = requests.get(
            f"{SLACK_API}/users.lookupByEmail",
            headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
            params={"email": email},
            timeout=5,
        )
        data = r.json() or {}
        if data.get("ok"):
            return (data.get("user") or {}).get("id")
    except Exception:
        logger.exception("slack users.lookupByEmail failed")
    return None


def _slack_post_dm(user_id: str, text: str, blocks: Optional[list] = None) -> tuple[bool, Optional[str]]:
    if not settings.slack_bot_token:
        return False, "slack_bot_token not configured"
    payload: dict[str, Any] = {"channel": user_id, "text": text}
    if blocks:
        payload["blocks"] = blocks
    try:
        r = requests.post(
            f"{SLACK_API}/chat.postMessage",
            headers={
                "Authorization": f"Bearer {settings.slack_bot_token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json=payload,
            timeout=10,
        )
        data = r.json() or {}
        if data.get("ok"):
            return True, None
        return False, data.get("error") or f"HTTP {r.status_code}"
    except Exception as exc:
        return False, str(exc)


def send_slack_dm_to_email(
    db: Session,
    recipient_email: str,
    subject_type: str,
    subject_id: str,
    text: str,
    blocks: Optional[list] = None,
    bypass_rate_limit: bool = False,
    bypass_quiet_hours: bool = False,
) -> bool:
    """Send a Slack DM if we haven't already sent this subject to this person
    and we're under the hourly rate limit.
    """
    if not is_enabled():
        return False
    try:
        assert_allowed(recipient_email)
    except UnauthorizedRecipientError:
        logger.exception("push: blocking DM — %s is not on the KPI allowlist", recipient_email)
        return False
    user_id = _slack_user_id_by_email(db, recipient_email)
    if not user_id:
        logger.info("push: no slack user_id for %s — skipping", recipient_email)
        return False

    if _already_sent(db, "slack", subject_type, subject_id, user_id):
        return False

    if not bypass_quiet_hours and is_quiet_hour():
        logger.info("push: quiet-hour skip for %s subject=%s", user_id, subject_id)
        return False

    if not bypass_rate_limit:
        recent = _recent_send_count(db, user_id, minutes=60)
        if recent >= settings.push_alerts_max_per_hour:
            logger.info("push: rate limit hit for %s (%d in last hour)", user_id, recent)
            return False

    ok, err = _slack_post_dm(user_id, text, blocks)
    _record_send(db, "slack", user_id, subject_type, subject_id, ok, err,
                 metadata={"recipient_email": recipient_email})
    db.commit()
    return ok


# ---------------------------------------------------------------------------
# Real-time push for IssueSignals
# ---------------------------------------------------------------------------

def _signal_dm_text(signal: IssueSignal) -> str:
    meta = signal.metadata_json or {}
    ai = meta.get("ai") if isinstance(meta, dict) else None
    title = (ai or {}).get("title") or signal.title or signal.signal_type
    summary = (ai or {}).get("summary") or signal.summary or ""
    source = signal.source or "system"
    parts = [f":rotating_light: *{title}*", f"_{source} · {signal.signal_type} · {signal.severity}_"]
    if summary:
        parts.append(summary[:500])
    if meta.get("url"):
        parts.append(f"<{meta['url']}|Open in ClickUp>")
    elif meta.get("channel_id") and meta.get("message_ts"):
        parts.append(f"Source: Slack channel {meta['channel_id']}")
    parts.append(f"<https://kpi.spidergrills.com/|Morning brief ↗>")
    return "\n".join(parts)


def push_critical_signal(db: Session, signal: IssueSignal) -> int:
    """DM each configured recipient about this critical signal. Returns count sent."""
    if not is_enabled():
        return 0
    if (signal.severity or "").lower() != "critical":
        return 0

    # AI veto: if the classifier called this team_chatter or not_applicable,
    # don't blast the DM — the keyword rule over-fired.
    meta = signal.metadata_json or {}
    ai = meta.get("ai") if isinstance(meta, dict) else None
    if isinstance(ai, dict):
        if ai.get("classification") in {"team_chatter", "not_applicable", "question_pending"}:
            return 0
        if ai.get("is_draft_worthy") is False:
            return 0

    raw_emails = [e.strip() for e in (settings.push_alerts_slack_recipient_emails or "").split(",") if e.strip()]
    if not raw_emails:
        return 0
    try:
        emails = assert_allowed(raw_emails)
    except UnauthorizedRecipientError:
        logger.exception(
            "push: blocking critical-signal DM — configured recipients are not on the KPI allowlist"
        )
        return 0

    text = _signal_dm_text(signal)
    sent = 0
    subject_id = str(signal.id)
    for email in emails:
        if send_slack_dm_to_email(db, email, "issue_signal", subject_id, text):
            sent += 1
    return sent
