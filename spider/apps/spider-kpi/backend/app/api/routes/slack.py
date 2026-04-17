"""Slack API + webhook routes.

Three surfaces:

* ``POST /api/webhooks/slack/events`` — Slack Events API receiver. Verifies
  signature, handles the url_verification challenge, and dispatches events
  (message, reaction, channel change, user change) into the connector.

* ``GET  /api/slack/files/{file_id}`` — streaming proxy for Slack-hosted
  images / videos. Uses the bot token server-side so the browser never sees
  it, and we don't duplicate file storage.

* ``GET  /api/slack/{channels,pulse,messages}`` — read endpoints the
  ``<SlackPulseCard>`` component consumes.

All non-webhook endpoints are guarded by the dashboard session cookie; the
webhook endpoint is public (Slack's signature is the auth).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import requests
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_dashboard_session
from app.core.config import get_settings
from app.ingestion.connectors.slack import (
    backfill_channel,
    discover_channels,
    discover_users,
    rebuild_activity_daily,
    scan_messages_for_issues,
    sync_slack,
    upsert_message,
    upsert_reaction,
)
from app.models import (
    SlackActivityDaily,
    SlackChannel,
    SlackFile,
    SlackMessage,
    SlackUser,
)


settings = get_settings()
logger = logging.getLogger(__name__)
BUSINESS_TZ = ZoneInfo("America/New_York")

# Public webhook router (no auth — signature is the auth)
webhook_router = APIRouter(prefix="/api/webhooks/slack", tags=["slack_webhook"])

# Dashboard-authenticated API router
router = APIRouter(
    prefix="/api/slack",
    tags=["slack"],
    dependencies=[Depends(require_dashboard_session)],
)


# ---------------------------------------------------------------------------
# Webhook signature verification
# ---------------------------------------------------------------------------

def _verify_slack_signature(timestamp: str, body: bytes, signature: str) -> bool:
    if not settings.slack_signing_secret:
        return False
    try:
        ts_int = int(timestamp)
    except (TypeError, ValueError):
        return False
    # Reject messages older than 5 min (replay protection)
    if abs(time.time() - ts_int) > 300:
        return False
    basestring = b"v0:" + timestamp.encode() + b":" + body
    digest = hmac.new(
        settings.slack_signing_secret.encode(),
        basestring,
        hashlib.sha256,
    ).hexdigest()
    expected = f"v0={digest}"
    return hmac.compare_digest(expected, signature or "")


# ---------------------------------------------------------------------------
# Webhook — Events API
# ---------------------------------------------------------------------------

@webhook_router.post("/events")
async def slack_events(request: Request, db: Session = Depends(db_session)) -> Any:
    body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not _verify_slack_signature(timestamp, body, signature):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    payload = await request.json()
    event_type = payload.get("type")

    # URL verification handshake (run once when the Event URL is set in the
    # Slack app). Slack expects the challenge echoed verbatim.
    if event_type == "url_verification":
        return {"challenge": payload.get("challenge")}

    if event_type != "event_callback":
        return {"ok": True}

    event = payload.get("event") or {}
    outer_event_id = payload.get("event_id")
    try:
        _handle_event(db, event, outer_event_id=outer_event_id)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("slack event handling failed: %s", event.get("type"))
        # Slack retries on 500 — we choose to swallow rather than replay loop.
    return Response(status_code=200)


def _handle_event(db: Session, event: dict[str, Any], outer_event_id: str | None = None) -> None:
    et = event.get("type")
    if et == "message":
        channel_id = event.get("channel")
        if not channel_id:
            return
        # Ignore our own bot's posts to avoid echo loops
        bot_user_id = None  # If/when we post back, wire in `auth.test` caching
        if event.get("bot_id") and bot_user_id and event.get("user") == bot_user_id:
            return
        upsert_message(db, channel_id, event)
    elif et == "reaction_added":
        item = event.get("item") or {}
        if item.get("type") == "message":
            upsert_reaction(
                db,
                channel_id=item.get("channel"),
                message_ts=item.get("ts"),
                user_id=event.get("user"),
                name=event.get("reaction"),
                added=True,
                event_ts=event.get("event_ts"),
            )
    elif et == "reaction_removed":
        item = event.get("item") or {}
        if item.get("type") == "message":
            upsert_reaction(
                db,
                channel_id=item.get("channel"),
                message_ts=item.get("ts"),
                user_id=event.get("user"),
                name=event.get("reaction"),
                added=False,
            )
    elif et in {"channel_created", "channel_rename", "channel_archive", "channel_unarchive"}:
        # Let the next scheduled discovery tick refresh channel metadata —
        # these events are rare and we don't need perfect real-time state.
        ch = event.get("channel") or {}
        channel_id = ch.get("id") if isinstance(ch, dict) else ch
        if channel_id:
            existing = db.execute(select(SlackChannel).where(SlackChannel.channel_id == channel_id)).scalars().first()
            if existing is None:
                existing = SlackChannel(channel_id=channel_id)
                db.add(existing)
            if isinstance(ch, dict):
                existing.name = ch.get("name") or existing.name
                existing.is_archived = et == "channel_archive"
                existing.last_synced_at = datetime.now(timezone.utc)
                existing.raw_payload = ch
    elif et == "team_join" or et == "user_change":
        u = event.get("user") or {}
        uid = u.get("id") if isinstance(u, dict) else None
        if uid:
            row = db.execute(select(SlackUser).where(SlackUser.user_id == uid)).scalars().first()
            if row is None:
                row = SlackUser(user_id=uid)
                db.add(row)
            profile = u.get("profile") or {}
            row.name = u.get("name")
            row.real_name = profile.get("real_name")
            row.display_name = profile.get("display_name")
            row.email = profile.get("email")
            row.is_bot = bool(u.get("is_bot"))
            row.is_deleted = bool(u.get("deleted"))
            row.last_synced_at = datetime.now(timezone.utc)
            row.raw_payload = u


# ---------------------------------------------------------------------------
# File proxy — streams Slack-hosted bytes through our backend
# ---------------------------------------------------------------------------

@router.get("/files/{file_id}")
def slack_file_proxy(file_id: str, db: Session = Depends(db_session)):
    row = db.execute(select(SlackFile).where(SlackFile.file_id == file_id)).scalars().first()
    if row is None or not row.url_private:
        raise HTTPException(status_code=404, detail="File not found")
    if not settings.slack_bot_token:
        raise HTTPException(status_code=503, detail="Slack not configured")

    upstream = requests.get(
        row.url_private,
        headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
        stream=True,
        timeout=30,
    )
    if upstream.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Slack file fetch failed ({upstream.status_code})")

    def iter_bytes():
        try:
            for chunk in upstream.iter_content(chunk_size=32 * 1024):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    headers = {
        "Cache-Control": "private, max-age=86400",
        "Content-Disposition": f'inline; filename="{row.name or file_id}"',
    }
    return StreamingResponse(
        iter_bytes(),
        media_type=row.mimetype or upstream.headers.get("Content-Type") or "application/octet-stream",
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Read endpoints for the frontend
# ---------------------------------------------------------------------------

def _channel_summary(row: SlackChannel) -> dict[str, Any]:
    return {
        "channel_id": row.channel_id,
        "name": row.name,
        "is_private": row.is_private,
        "is_archived": row.is_archived,
        "is_member": row.is_member,
        "num_members": row.num_members,
        "topic": row.topic,
        "purpose": row.purpose,
    }


def _message_summary(m: SlackMessage, user_map: dict[str, SlackUser]) -> dict[str, Any]:
    u = user_map.get(m.user_id or "")
    return {
        "channel_id": m.channel_id,
        "ts": m.ts,
        "ts_dt": m.ts_dt.isoformat() if m.ts_dt else None,
        "thread_ts": m.thread_ts,
        "user_id": m.user_id,
        "user_name": (u.display_name or u.real_name or u.name) if u else None,
        "subtype": m.subtype,
        "text": m.text,
        "has_files": m.has_files,
        "file_count": m.file_count,
        "reaction_count": m.reaction_count,
        "reply_count": m.reply_count,
        "is_deleted": m.is_deleted,
    }


@router.get("/channels")
def list_channels(include_archived: bool = False, db: Session = Depends(db_session)) -> dict[str, Any]:
    stmt = select(SlackChannel)
    if not include_archived:
        stmt = stmt.where(SlackChannel.is_archived == False)  # noqa: E712
    stmt = stmt.order_by(SlackChannel.name)
    rows = db.execute(stmt).scalars().all()
    return {
        "channels": [_channel_summary(r) for r in rows],
        "configured": bool(settings.slack_bot_token),
    }


@router.get("/pulse")
def channel_pulse(channel_id: Optional[str] = None, days: int = 14, db: Session = Depends(db_session)) -> dict[str, Any]:
    days = max(1, min(days, 90))
    today = datetime.now(BUSINESS_TZ).date()
    start_date = today - timedelta(days=days - 1)

    stmt = select(SlackActivityDaily).where(
        SlackActivityDaily.business_date >= start_date,
        SlackActivityDaily.business_date <= today,
    )
    if channel_id:
        stmt = stmt.where(SlackActivityDaily.channel_id == channel_id)
    stmt = stmt.order_by(SlackActivityDaily.business_date)
    rows = db.execute(stmt).scalars().all()

    # Latest message lookup (bounded)
    latest_msg_stmt = select(SlackMessage).where(SlackMessage.is_deleted == False)  # noqa: E712
    if channel_id:
        latest_msg_stmt = latest_msg_stmt.where(SlackMessage.channel_id == channel_id)
    latest_msg = db.execute(latest_msg_stmt.order_by(desc(SlackMessage.ts_dt)).limit(1)).scalars().first()

    # User map for the latest message rendering
    user_map = {}
    if latest_msg and latest_msg.user_id:
        u = db.execute(select(SlackUser).where(SlackUser.user_id == latest_msg.user_id)).scalars().first()
        if u:
            user_map[u.user_id] = u

    # Roll up window-level
    total_messages = sum(r.message_count for r in rows)
    total_reactions = sum(r.reaction_count for r in rows)
    total_files = sum(r.file_count for r in rows)
    total_replies = sum(r.reply_count for r in rows)
    unique_user_ids: set[str] = set()
    for r in rows:
        for u in r.top_users_json or []:
            if u.get("user_id"):
                unique_user_ids.add(u["user_id"])

    channel_meta = None
    if channel_id:
        ch = db.execute(select(SlackChannel).where(SlackChannel.channel_id == channel_id)).scalars().first()
        if ch:
            channel_meta = _channel_summary(ch)

    return {
        "window": {"start": start_date.isoformat(), "end": today.isoformat(), "days": days},
        "channel": channel_meta,
        "totals": {
            "messages": total_messages,
            "reactions": total_reactions,
            "files": total_files,
            "replies": total_replies,
            "unique_users_seen": len(unique_user_ids),
        },
        "daily": [
            {
                "business_date": r.business_date.isoformat(),
                "channel_id": r.channel_id,
                "channel_name": r.channel_name,
                "message_count": r.message_count,
                "unique_users": r.unique_users,
                "reaction_count": r.reaction_count,
                "thread_count": r.thread_count,
                "reply_count": r.reply_count,
                "file_count": r.file_count,
                "peak_hour": r.peak_hour,
            }
            for r in rows
        ],
        "latest_message": _message_summary(latest_msg, user_map) if latest_msg else None,
        "configured": bool(settings.slack_bot_token),
    }


@router.get("/messages")
def list_messages(
    channel_id: Optional[str] = None,
    thread_ts: Optional[str] = None,
    q: Optional[str] = None,
    since_days: Optional[int] = None,
    limit: int = 50,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    limit = max(1, min(limit, 500))
    stmt = select(SlackMessage).where(SlackMessage.is_deleted == False)  # noqa: E712
    if channel_id:
        stmt = stmt.where(SlackMessage.channel_id == channel_id)
    if thread_ts:
        stmt = stmt.where(SlackMessage.thread_ts == thread_ts)
    if q:
        stmt = stmt.where(SlackMessage.text.ilike(f"%{q}%"))
    if since_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        stmt = stmt.where(SlackMessage.ts_dt >= cutoff)
    stmt = stmt.order_by(desc(SlackMessage.ts_dt)).limit(limit)
    msgs = db.execute(stmt).scalars().all()

    # Bulk user map
    user_ids = {m.user_id for m in msgs if m.user_id}
    user_map: dict[str, SlackUser] = {}
    if user_ids:
        rows = db.execute(select(SlackUser).where(SlackUser.user_id.in_(user_ids))).scalars().all()
        user_map = {u.user_id: u for u in rows}

    return {
        "messages": [_message_summary(m, user_map) for m in msgs],
    }


@router.post("/sync-now")
def slack_sync_now(full: bool = False, db: Session = Depends(db_session)) -> dict[str, Any]:
    return sync_slack(db, full=full)


@router.get("/config")
def slack_config() -> dict[str, Any]:
    return {
        "configured": bool(settings.slack_bot_token and settings.slack_signing_secret),
        "team_id": settings.slack_team_id,
        "app_id": settings.slack_app_id,
    }
