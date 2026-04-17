"""Slack connector for the Spider KPI dashboard.

Responsibilities:

* **Discovery**: list channels (public + private the bot is in), list users.
  Channels are auto-picked-up as they're created, so no manual channel list
  lives in config.
* **Backfill**: on first run (and on demand) pull recent history per channel
  to seed the archive.
* **Real-time ingestion**: called from the Events API webhook, upserts a
  single message, reaction, or file into the tables.
* **Rollup**: recomputes ``slack_activity_daily`` for a given date range.
* **Issue scan**: surfaces messages matching an issue pattern set as
  ``IssueSignal`` rows with ``source='slack'`` so they feed Issue Radar.

All HTTP calls use a pooled ``requests`` session with Bearer auth and
respect Slack's rate limits (Retry-After).
"""
from __future__ import annotations

import logging
import re
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    IssueSignal,
    SlackActivityDaily,
    SlackChannel,
    SlackFile,
    SlackMessage,
    SlackReaction,
    SlackUser,
)
from app.services.source_health import finish_sync_run, start_sync_run, upsert_source_config


settings = get_settings()
logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter('%(levelname)s:%(name)s:%(message)s'))
    logger.addHandler(sh)

TIMEOUT_SECONDS = 30
BUSINESS_TZ = ZoneInfo("America/New_York")
SOURCE_NAME = "slack"

SLACK_API = "https://slack.com/api"

# Default issue-detection patterns. Tuned on Spider Grills workflow language;
# extend freely. Matches are case-insensitive.
DEFAULT_ISSUE_PATTERNS: list[dict[str, str]] = [
    {"name": "broken", "severity": "warning", "regex": r"\b(broken|doesn['’]?t work|not working|stopped working)\b"},
    {"name": "crash", "severity": "critical", "regex": r"\b(crash(ed|ing)?|hang(s|ing)?|frozen|locked up)\b"},
    {"name": "error_word", "severity": "warning", "regex": r"\b(error|exception|fail(ed|ing|ure)?)\b"},
    {"name": "customer_complaint", "severity": "warning", "regex": r"\b(customer (complaint|complained|angry|upset)|complaint from)\b"},
    {"name": "refund_request", "severity": "warning", "regex": r"\b(refund|chargeback|return requested)\b"},
    {"name": "venom_fault", "severity": "critical", "regex": r"\bvenom\b.*\b(not|won['’]?t|can['’]?t|fail|error|broken)\b"},
    {"name": "firmware_concern", "severity": "warning", "regex": r"\b(firmware|update|rollback).*\b(bad|broken|issue|bug|fail|revert)\b"},
    {"name": "urgent_ping", "severity": "critical", "regex": r"(<!channel>|<!here>|\b(urgent|asap|emergency|p0)\b)"},
    {"name": "help_request", "severity": "info", "regex": r"\b(need help|please help|someone help|halp)\b"},
]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _configured() -> bool:
    return bool(settings.slack_bot_token)


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.slack_bot_token or ''}",
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
    }


def _call(method: str, params: dict[str, Any] | None = None, *, http_method: str = "GET") -> dict[str, Any]:
    """Call a Slack API method with rate-limit handling and basic retry."""
    url = f"{SLACK_API}/{method}"
    attempts = 0
    while True:
        attempts += 1
        if http_method == "GET":
            r = requests.get(url, headers=_headers(), params=params or {}, timeout=TIMEOUT_SECONDS)
        else:
            r = requests.post(url, headers=_headers(), json=params or {}, timeout=TIMEOUT_SECONDS)
        if r.status_code == 429:
            retry = float(r.headers.get("Retry-After") or "2")
            logger.warning("slack rate-limited on %s, sleeping %.1fs", method, retry)
            time.sleep(retry)
            if attempts > 5:
                r.raise_for_status()
            continue
        r.raise_for_status()
        payload = r.json()
        if not payload.get("ok"):
            logger.warning("slack API error on %s: %s", method, payload.get("error"))
        return payload


def _ts_to_dt(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def _business_date(value: datetime | None) -> date | None:
    if value is None:
        return None
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(BUSINESS_TZ).date()


_MENTION_RE = re.compile(r"<@([A-Z0-9]+)(?:\|[^>]+)?>")


def _extract_mentions(text: str | None) -> list[str]:
    if not text:
        return []
    return list({m for m in _MENTION_RE.findall(text)})


# ---------------------------------------------------------------------------
# Channel / user discovery
# ---------------------------------------------------------------------------

def discover_channels(db: Session) -> dict[str, int]:
    """Pull public + private channels the bot is in; upsert SlackChannel rows.

    Calls ``conversations.list`` once per type so a missing scope on one type
    (typically ``groups:read`` for private channels when it wasn't installed)
    doesn't block discovery of the other. Scope-denied types are recorded
    but do not error the whole sync.
    """
    stats = {"channels_seen": 0, "channels_inserted": 0, "channels_updated": 0, "scopes_missing": []}

    def _pull(channel_type: str) -> None:
        cursor = ""
        while True:
            params = {"limit": 200, "types": channel_type, "exclude_archived": False}
            if cursor:
                params["cursor"] = cursor
            data = _call("conversations.list", params)
            if not data.get("ok"):
                err = data.get("error") or "unknown"
                if err == "missing_scope":
                    needed = data.get("needed") or ""
                    logger.warning(
                        "slack conversations.list %s failed: missing scope %s — "
                        "install the app with this scope to enable %s channel visibility",
                        channel_type, needed, channel_type,
                    )
                    stats["scopes_missing"].append({"type": channel_type, "needed": needed})
                else:
                    logger.warning("slack conversations.list %s failed: %s", channel_type, err)
                return
            for ch in data.get("channels") or []:
                stats["channels_seen"] += 1
                row = db.execute(select(SlackChannel).where(SlackChannel.channel_id == ch["id"])).scalars().first()
                if row is None:
                    row = SlackChannel(channel_id=ch["id"])
                    db.add(row)
                    stats["channels_inserted"] += 1
                else:
                    stats["channels_updated"] += 1
                row.name = ch.get("name")
                row.is_private = bool(ch.get("is_private"))
                row.is_archived = bool(ch.get("is_archived"))
                row.is_member = bool(ch.get("is_member"))
                topic = (ch.get("topic") or {}).get("value") if isinstance(ch.get("topic"), dict) else None
                purpose = (ch.get("purpose") or {}).get("value") if isinstance(ch.get("purpose"), dict) else None
                row.topic = topic
                row.purpose = purpose
                row.num_members = ch.get("num_members")
                row.created_at_source = _ts_to_dt(str(ch.get("created"))) if ch.get("created") else None
                row.last_synced_at = datetime.now(timezone.utc)
                row.raw_payload = ch
            cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
            if not cursor:
                return

    _pull("public_channel")
    _pull("private_channel")
    db.flush()
    return stats


def discover_users(db: Session) -> dict[str, int]:
    stats = {"users_seen": 0, "users_inserted": 0, "users_updated": 0}
    cursor = ""
    while True:
        params = {"limit": 200}
        if cursor:
            params["cursor"] = cursor
        data = _call("users.list", params)
        for u in data.get("members") or []:
            stats["users_seen"] += 1
            row = db.execute(select(SlackUser).where(SlackUser.user_id == u["id"])).scalars().first()
            if row is None:
                row = SlackUser(user_id=u["id"])
                db.add(row)
                stats["users_inserted"] += 1
            else:
                stats["users_updated"] += 1
            profile = u.get("profile") or {}
            row.name = u.get("name")
            row.real_name = profile.get("real_name")
            row.display_name = profile.get("display_name") or profile.get("display_name_normalized")
            row.email = profile.get("email")
            row.tz = u.get("tz")
            row.title = profile.get("title")
            row.is_bot = bool(u.get("is_bot"))
            row.is_app_user = bool(u.get("is_app_user"))
            row.is_admin = bool(u.get("is_admin"))
            row.is_deleted = bool(u.get("deleted"))
            row.last_synced_at = datetime.now(timezone.utc)
            row.raw_payload = u
        cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            break
    db.flush()
    return stats


# ---------------------------------------------------------------------------
# Message upsert (shared by backfill + webhook)
# ---------------------------------------------------------------------------

def upsert_message(db: Session, channel_id: str, event: dict[str, Any]) -> tuple[SlackMessage | None, bool]:
    """Insert or update a single message event. Returns (row, inserted)."""
    ts = event.get("ts")
    if not ts:
        return None, False

    subtype = event.get("subtype")

    # Slack re-delivers edits as `message_changed` with a nested "message" +
    # "previous_message". Unwrap so we always work with the final state.
    if subtype == "message_changed":
        inner = event.get("message") or {}
        inner_ts = inner.get("ts") or ts
        row = db.execute(select(SlackMessage).where(
            SlackMessage.channel_id == channel_id,
            SlackMessage.ts == inner_ts,
        )).scalars().first()
        if row is None:
            row = SlackMessage(channel_id=channel_id, ts=inner_ts, ts_dt=_ts_to_dt(inner_ts) or datetime.now(timezone.utc))
            db.add(row)
        row.user_id = inner.get("user") or row.user_id
        row.text = inner.get("text")
        edited = inner.get("edited") or {}
        row.edited_user_id = edited.get("user")
        row.edited_ts = edited.get("ts")
        row.thread_ts = inner.get("thread_ts") or row.thread_ts
        row.raw_payload = inner
        row.mentions_json = _extract_mentions(inner.get("text"))
        return row, False

    if subtype == "message_deleted":
        del_ts = event.get("deleted_ts")
        row = db.execute(select(SlackMessage).where(
            SlackMessage.channel_id == channel_id,
            SlackMessage.ts == del_ts,
        )).scalars().first()
        if row is not None:
            row.is_deleted = True
        return row, False

    # Regular message
    row = db.execute(select(SlackMessage).where(
        SlackMessage.channel_id == channel_id,
        SlackMessage.ts == ts,
    )).scalars().first()
    inserted = False
    if row is None:
        row = SlackMessage(channel_id=channel_id, ts=ts, ts_dt=_ts_to_dt(ts) or datetime.now(timezone.utc))
        db.add(row)
        inserted = True

    row.thread_ts = event.get("thread_ts")
    row.parent_user_id = event.get("parent_user_id")
    row.user_id = event.get("user")
    row.bot_id = event.get("bot_id")
    row.subtype = subtype
    row.text = event.get("text")
    edited = event.get("edited") or {}
    row.edited_user_id = edited.get("user")
    row.edited_ts = edited.get("ts")
    row.has_files = bool(event.get("files"))
    row.file_count = len(event.get("files") or [])
    row.reaction_count = sum(int((r or {}).get("count") or 0) for r in (event.get("reactions") or []))
    row.reply_count = int(event.get("reply_count") or 0)
    row.mentions_json = _extract_mentions(event.get("text"))
    row.raw_payload = event

    # Fan out file metadata. Use Postgres INSERT ... ON CONFLICT because a
    # single backfill often re-references the same file across multiple
    # messages in the same flush (e.g. a recurring inventory spreadsheet),
    # and Session.add() within the same transaction can't rely on the
    # previous INSERT being visible until flush.
    for f in event.get("files") or []:
        if not isinstance(f, dict) or not f.get("id"):
            continue
        payload = {
            "file_id": f["id"],
            "channel_id": channel_id,
            "message_ts": ts,
            "user_id": f.get("user"),
            "name": f.get("name"),
            "title": f.get("title"),
            "mimetype": f.get("mimetype"),
            "filetype": f.get("filetype"),
            "size": f.get("size"),
            "url_private": f.get("url_private"),
            "url_private_download": f.get("url_private_download"),
            "thumb_url": f.get("thumb_360") or f.get("thumb_720"),
            "created_at_source": _ts_to_dt(str(f.get("created"))) if f.get("created") else None,
            "raw_payload": f,
        }
        stmt = pg_insert(SlackFile).values(**payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=[SlackFile.file_id],
            set_={k: v for k, v in payload.items() if k != "file_id"},
        )
        db.execute(stmt)

    return row, inserted


def upsert_reaction(db: Session, channel_id: str, message_ts: str, user_id: str, name: str, added: bool, event_ts: str | None = None) -> None:
    if added:
        existing = db.execute(select(SlackReaction).where(
            SlackReaction.channel_id == channel_id,
            SlackReaction.message_ts == message_ts,
            SlackReaction.user_id == user_id,
            SlackReaction.name == name,
        )).scalars().first()
        if existing is None:
            db.add(SlackReaction(
                channel_id=channel_id, message_ts=message_ts,
                user_id=user_id, name=name,
                reacted_at=_ts_to_dt(event_ts) or datetime.now(timezone.utc),
            ))
    else:
        db.execute(delete(SlackReaction).where(
            SlackReaction.channel_id == channel_id,
            SlackReaction.message_ts == message_ts,
            SlackReaction.user_id == user_id,
            SlackReaction.name == name,
        ))


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------

def backfill_channel(db: Session, channel_id: str, lookback_days: int | None = None) -> dict[str, int]:
    """Pull conversation history for a channel (plus thread replies) and upsert.

    Uses ``conversations.history`` with an oldest ts filter so we can cap the
    backfill window.
    """
    stats = {"messages_fetched": 0, "messages_inserted": 0, "threads_fetched": 0}
    lookback = lookback_days if lookback_days is not None else settings.slack_backfill_days
    oldest = (datetime.now(timezone.utc) - timedelta(days=lookback)).timestamp()

    cursor = ""
    while True:
        params = {"channel": channel_id, "limit": 200, "oldest": str(oldest), "inclusive": "true"}
        if cursor:
            params["cursor"] = cursor
        data = _call("conversations.history", params)
        for msg in data.get("messages") or []:
            stats["messages_fetched"] += 1
            _, inserted = upsert_message(db, channel_id, msg)
            if inserted:
                stats["messages_inserted"] += 1
            # Flush so the next select-before-insert in upsert_message sees
            # this row — Slack's replies endpoint can return a message we
            # already inserted from the history page, and pending Session.add
            # rows aren't visible to further selects until flush.
            db.flush()
            # Thread roots -> pull replies
            if msg.get("thread_ts") and msg.get("reply_count"):
                for reply in _iter_thread_replies(channel_id, msg["thread_ts"]):
                    stats["threads_fetched"] += 1
                    _, r_inserted = upsert_message(db, channel_id, reply)
                    if r_inserted:
                        stats["messages_inserted"] += 1
                    db.flush()
        cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            break

    db.flush()
    return stats


def _iter_thread_replies(channel_id: str, thread_ts: str) -> Iterable[dict[str, Any]]:
    cursor = ""
    first = True
    while True:
        params = {"channel": channel_id, "ts": thread_ts, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        data = _call("conversations.replies", params)
        for msg in data.get("messages") or []:
            # Skip the parent itself on the first page — already upserted in backfill.
            if first and msg.get("ts") == thread_ts:
                first = False
                continue
            first = False
            yield msg
        cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            return


# ---------------------------------------------------------------------------
# Daily rollup
# ---------------------------------------------------------------------------

def rebuild_activity_daily(db: Session, start_date: date, end_date: date) -> int:
    if start_date > end_date:
        return 0

    # Preload channel name map
    channel_names = dict(db.execute(
        select(SlackChannel.channel_id, SlackChannel.name)
    ).all())

    # Pull messages in range
    start_dt = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=BUSINESS_TZ)
    end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time()).replace(tzinfo=BUSINESS_TZ)
    msgs = db.execute(select(SlackMessage).where(
        SlackMessage.ts_dt >= start_dt,
        SlackMessage.ts_dt < end_dt,
        SlackMessage.is_deleted == False,  # noqa: E712
    )).scalars().all()

    grouped: dict[tuple[date, str], dict[str, Any]] = defaultdict(lambda: {
        "message_count": 0,
        "user_counter": Counter(),
        "reaction_count": 0,
        "thread_roots": set(),
        "reply_count": 0,
        "file_count": 0,
        "hour_counter": Counter(),
    })

    for m in msgs:
        bd = _business_date(m.ts_dt)
        if bd is None or not (start_date <= bd <= end_date):
            continue
        key = (bd, m.channel_id)
        g = grouped[key]
        g["message_count"] += 1
        if m.user_id:
            g["user_counter"][m.user_id] += 1
        g["reaction_count"] += int(m.reaction_count or 0)
        g["file_count"] += int(m.file_count or 0)
        if m.thread_ts:
            if m.thread_ts == m.ts:
                g["thread_roots"].add(m.ts)
            else:
                g["reply_count"] += 1
        hour = m.ts_dt.astimezone(BUSINESS_TZ).hour
        g["hour_counter"][hour] += 1

    # Wipe target window for each channel present, rewrite.
    db.execute(delete(SlackActivityDaily).where(
        SlackActivityDaily.business_date >= start_date,
        SlackActivityDaily.business_date <= end_date,
    ))
    db.flush()

    rows_written = 0
    for (bd, channel_id), g in grouped.items():
        peak = g["hour_counter"].most_common(1)[0][0] if g["hour_counter"] else None
        top_users = [{"user_id": u, "count": c} for u, c in g["user_counter"].most_common(5)]
        db.add(SlackActivityDaily(
            business_date=bd,
            channel_id=channel_id,
            channel_name=channel_names.get(channel_id),
            message_count=g["message_count"],
            unique_users=len(g["user_counter"]),
            reaction_count=g["reaction_count"],
            thread_count=len(g["thread_roots"]),
            reply_count=g["reply_count"],
            file_count=g["file_count"],
            peak_hour=peak,
            hour_histogram={str(h): c for h, c in g["hour_counter"].items()},
            top_users_json=top_users,
        ))
        rows_written += 1

    db.flush()
    return rows_written


# ---------------------------------------------------------------------------
# Issue-pattern scan
# ---------------------------------------------------------------------------

def scan_messages_for_issues(db: Session, since: datetime | None = None, patterns: list[dict[str, str]] | None = None) -> int:
    """Scan messages newer than ``since`` for issue-shaped language and write
    matching rows into ``issue_signals`` with ``source='slack'``. Deduped by
    (signal_type, metadata_json.channel_id, metadata_json.message_ts).
    """
    patterns = patterns or DEFAULT_ISSUE_PATTERNS
    compiled = [(p["name"], p["severity"], re.compile(p["regex"], re.IGNORECASE)) for p in patterns]

    if since is None:
        since = datetime.now(timezone.utc) - timedelta(days=2)

    msgs = db.execute(select(SlackMessage).where(
        SlackMessage.ts_dt >= since,
        SlackMessage.is_deleted == False,  # noqa: E712
    )).scalars().all()

    inserted = 0
    for m in msgs:
        if not m.text:
            continue
        for name, severity, rx in compiled:
            if not rx.search(m.text):
                continue
            # Dedup by (source, channel_id, ts, pattern)
            existing = db.execute(select(IssueSignal).where(
                IssueSignal.source == SOURCE_NAME,
                IssueSignal.signal_type == f"slack.{name}",
                IssueSignal.metadata_json["channel_id"].astext == m.channel_id,
                IssueSignal.metadata_json["message_ts"].astext == m.ts,
            )).scalars().first()
            if existing is not None:
                continue
            signal_meta = {
                "channel_id": m.channel_id,
                "message_ts": m.ts,
                "user_id": m.user_id,
                "pattern": name,
                "thread_ts": m.thread_ts,
            }
            new_signal = IssueSignal(
                business_date=_business_date(m.ts_dt),
                signal_type=f"slack.{name}",
                severity=severity,
                confidence=0.6,  # keyword-based baseline; AI bumps/drops below.
                source=SOURCE_NAME,
                title=(m.text or "")[:120] or f"Slack {name}",
                summary=(m.text or "")[:500],
                metadata_json=signal_meta,
            )
            # AI classification — enriches metadata with a clean title, refined
            # severity, and a draft-worthiness verdict. Fails silent if unconfigured.
            try:
                from app.services.ai_classifier import classify_signal, classification_to_metadata
                ai = classify_signal({
                    "source": SOURCE_NAME,
                    "signal_type": new_signal.signal_type,
                    "severity": new_signal.severity,
                    "title": new_signal.title,
                    "summary": new_signal.summary,
                    "metadata_json": signal_meta,
                })
                if ai is not None:
                    new_signal.metadata_json = {**signal_meta, "ai": classification_to_metadata(ai)}
                    # Refine severity + confidence in-place when AI has a strong read.
                    new_signal.severity = ai.severity
                    new_signal.confidence = ai.confidence
            except Exception:
                logger.exception("AI classification threw (non-fatal)")

            db.add(new_signal)
            inserted += 1
            break  # one signal per message is enough

    db.flush()
    return inserted


# ---------------------------------------------------------------------------
# Top-level sync
# ---------------------------------------------------------------------------

def sync_slack(db: Session, full: bool = False) -> dict[str, Any]:
    """Discover channels + users, backfill recent messages, rebuild rollup, scan.

    Safe to run repeatedly; backfill uses oldest=ts so it's bounded.
    """
    started = time.monotonic()
    upsert_source_config(
        db, SOURCE_NAME,
        configured=_configured(),
        sync_mode="events+poll",
        config_json={"team_id": settings.slack_team_id, "backfill_days": settings.slack_backfill_days},
    )
    db.commit()
    if not _configured():
        return {"ok": False, "message": "Slack not configured", "records_processed": 0}

    run = start_sync_run(db, SOURCE_NAME, "poll_full" if full else "poll_recent", {})
    db.commit()
    stats: dict[str, Any] = {}
    try:
        stats.update({"discover_channels": discover_channels(db)})
        stats.update({"discover_users": discover_users(db)})
        db.commit()

        # Backfill only channels the bot is a member of
        member_channels = db.execute(
            select(SlackChannel).where(SlackChannel.is_member == True, SlackChannel.is_archived == False)  # noqa: E712
        ).scalars().all()
        backfill_stats: dict[str, Any] = {}
        for ch in member_channels:
            bf = backfill_channel(db, ch.channel_id, lookback_days=settings.slack_backfill_days if not full else 365)
            backfill_stats[ch.name or ch.channel_id] = bf
            db.commit()
        stats["backfill"] = backfill_stats

        today = datetime.now(BUSINESS_TZ).date()
        rollup_start = today - timedelta(days=max(settings.slack_backfill_days, 30))
        rollup_written = rebuild_activity_daily(db, rollup_start, today)
        stats["rollup_rows_written"] = rollup_written
        db.commit()

        issues = scan_messages_for_issues(db, since=datetime.now(timezone.utc) - timedelta(days=settings.slack_backfill_days))
        stats["issue_signals_inserted"] = issues
        db.commit()

        # Feed the DECI auto-draft engine so new/updated signals flow into
        # draft decisions or update-logs on already-open ones.
        try:
            from app.compute.deci_autodraft import autodraft_from_signals
            stats["autodraft"] = autodraft_from_signals(
                db,
                since=datetime.now(timezone.utc) - timedelta(days=settings.slack_backfill_days),
            )
            db.commit()
        except Exception:
            logger.exception("slack autodraft failed (non-fatal)")
            db.rollback()

        duration_ms = int((time.monotonic() - started) * 1000)
        run = db.merge(run)
        run.metadata_json = {**(run.metadata_json or {}), **stats, "duration_ms": duration_ms}
        finish_sync_run(db, run, status="success",
                        records_processed=sum((b or {}).get("messages_fetched", 0) for b in (backfill_stats or {}).values()))
        db.commit()
        logger.info("slack sync complete: %s", stats)
        return {"ok": True, **stats, "duration_ms": duration_ms}
    except Exception as exc:
        db.rollback()
        run = db.merge(run)
        finish_sync_run(db, run, status="failed", error_message=str(exc))
        db.commit()
        logger.exception("slack sync failed")
        return {"ok": False, "message": str(exc), **stats}
