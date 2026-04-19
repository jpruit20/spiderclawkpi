"""Gmail archive ingestion — service account + domain-wide delegation.

Pulls messages from a Workspace mailbox (info@spidergrills.com today,
expandable to other shared inboxes later), normalizes + classifies them,
stores in ``email_messages`` with idempotency on the RFC Message-ID.

Two modes:

  * **Bulk historical**: ``ingest_history(since=date(2023,1,1))`` —
    paginated ``users.messages.list`` + batched ``messages.get``, one
    mailbox at a time. Idempotent; re-running skips already-stored
    message IDs.

  * **Daily incremental**: ``ingest_incremental()`` — uses
    ``users.history.list`` with the watermark saved in
    ``email_sync_state.last_history_id`` to fetch only what changed
    since the last run. Falls back to bulk if the watermark is stale
    (Gmail only retains ~7 days of history).

Designed for 65k+ message mailboxes without destroying memory —
messages are processed in chunks of 100, committed per chunk.
"""
from __future__ import annotations

import base64
import logging
import re
import time
from datetime import date, datetime, timezone
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from typing import Any, Iterable, Iterator, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import EmailMessage, EmailSyncState
from app.services.email_classifier import classify_email


logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
# Gmail allows batch sizes up to 100, BUT per-user concurrency limits kick
# in around ~20-30 parallel requests → 429 "Too many concurrent requests
# for user" on the rest. 25 is the sweet spot: fast throughput without
# hitting the concurrency wall.
BATCH_SIZE = 25
# Brief pause between batches — pacing, not throttle recovery.
INTER_BATCH_SLEEP_S = 0.25
# Retry budget for individual messages that 429'd within a batch.
RETRY_BACKOFFS_S = (2.0, 5.0, 12.0)
BODY_TEXT_MAX_CHARS = 500_000  # ~500KB of text, prevents runaway memory on pathological messages
PREVIEW_CHARS = 500


# ---------------------------------------------------------------------------
# Credentials + client
# ---------------------------------------------------------------------------

def _build_client(mailbox: str):
    settings = get_settings()
    key_path = getattr(settings, "gmail_service_account_key_path", None)
    if not key_path:
        # Fall through to os.environ for flexibility during development.
        import os
        key_path = os.environ.get("GMAIL_SERVICE_ACCOUNT_KEY_PATH")
    if not key_path:
        raise RuntimeError(
            "GMAIL_SERVICE_ACCOUNT_KEY_PATH is not set — cannot authenticate to Gmail API"
        )
    creds = service_account.Credentials.from_service_account_file(
        key_path, scopes=SCOPES
    ).with_subject(mailbox)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


# ---------------------------------------------------------------------------
# Payload normalization
# ---------------------------------------------------------------------------

def _decode_b64url(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s.encode("ascii"))


def _extract_text_and_attachments(payload: dict) -> tuple[str, list[dict]]:
    """Walk the MIME tree; return (plain_text_body, attachment_metadata_list).

    We keep text/plain only; HTML is dropped (text/plain is usually a
    sibling Gmail generates, and our classifier only reads plain). For
    attachments we record filename + MIME + size only — no binary blobs.
    """
    text_chunks: list[str] = []
    attachments: list[dict] = []

    def _walk(part: dict) -> None:
        mime = part.get("mimeType", "")
        filename = part.get("filename", "") or ""
        body = part.get("body", {}) or {}
        data = body.get("data")

        if filename and (body.get("attachmentId") or body.get("size")):
            attachments.append({
                "filename": filename,
                "mime_type": mime,
                "size_bytes": int(body.get("size") or 0),
                "attachment_id": body.get("attachmentId"),
            })
            return

        if mime == "text/plain" and data:
            try:
                text_chunks.append(_decode_b64url(data).decode("utf-8", errors="replace"))
            except Exception:
                pass
            return

        for child in part.get("parts", []) or []:
            _walk(child)

    _walk(payload)
    body_text = "\n\n".join(text_chunks)[:BODY_TEXT_MAX_CHARS]
    return body_text, attachments


def _parse_addresses(value: str) -> list[str]:
    if not value:
        return []
    return [addr for _name, addr in getaddresses([value]) if addr]


def _parse_sent_at(header_value: Optional[str], internal_date_ms: Optional[str]) -> Optional[datetime]:
    if header_value:
        try:
            dt = parsedate_to_datetime(header_value)
            if dt and dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            pass
    if internal_date_ms:
        try:
            return datetime.fromtimestamp(int(internal_date_ms) / 1000, tz=timezone.utc)
        except Exception:
            pass
    return None


def _domain_of(addr: str) -> str:
    _, email_part = parseaddr(addr or "")
    return email_part.rsplit("@", 1)[-1].lower() if "@" in email_part else ""


def _classify_direction(mailbox: str, from_address: str) -> str:
    return "outbound" if from_address.lower() == mailbox.lower() else "inbound"


def _normalize_message(mailbox: str, msg: dict) -> Optional[dict]:
    """Convert a Gmail API message JSON into an ``email_messages`` row dict.
    Returns None on unparseable input (rare)."""
    payload = msg.get("payload", {}) or {}
    headers = {h.get("name", "").lower(): h.get("value", "") for h in payload.get("headers", []) or []}
    message_id = headers.get("message-id") or f"gmail:{msg.get('id')}"
    subject = headers.get("subject") or ""
    from_hdr = headers.get("from") or ""
    _, from_addr = parseaddr(from_hdr)
    from_addr = from_addr.lower()
    to_addrs = _parse_addresses(headers.get("to") or "")
    cc_addrs = _parse_addresses(headers.get("cc") or "")
    sent_at = _parse_sent_at(headers.get("date"), msg.get("internalDate"))
    body_text, attachments = _extract_text_and_attachments(payload)
    snippet = msg.get("snippet") or ""
    preview = (body_text[:PREVIEW_CHARS] or snippet[:PREVIEW_CHARS]).strip()
    direction = _classify_direction(mailbox, from_addr)

    return {
        "message_id": message_id[:511],
        "gmail_message_id": msg.get("id"),
        "thread_id": msg.get("threadId"),
        "mailbox": mailbox,
        "sent_at": sent_at,
        "direction": direction,
        "from_address": from_addr[:511] if from_addr else None,
        "from_domain": _domain_of(from_addr)[:254] or None,
        "to_addresses": to_addrs,
        "cc_addresses": cc_addrs,
        "subject": subject[:4000] if subject else None,
        "body_text": body_text or None,
        "body_preview": preview or None,
        "snippet": snippet or None,
        "headers_json": {k: v for k, v in headers.items()},
        "labels_json": msg.get("labelIds", []) or [],
        "attachments_json": attachments,
        "raw_size_bytes": int(msg.get("sizeEstimate") or 0),
        "source": "gmail_api",
    }


# ---------------------------------------------------------------------------
# Ingest logic
# ---------------------------------------------------------------------------

def _load_existing_message_ids(db: Session, mailbox: str) -> set[str]:
    """Load every message_id already in the DB for this mailbox — used to
    skip duplicates on re-ingest. For 50k rows this is a ~5MB set, cheap."""
    rows = db.execute(
        select(EmailMessage.message_id, EmailMessage.gmail_message_id)
        .where(EmailMessage.mailbox == mailbox)
    ).all()
    out: set[str] = set()
    for rfc_id, gmail_id in rows:
        if rfc_id:
            out.add(rfc_id)
        if gmail_id:
            out.add(f"gmail:{gmail_id}")
    return out


def _iter_message_ids(svc, query: str) -> Iterator[str]:
    """Generator over Gmail message IDs matching a query, paginated."""
    page_token: Optional[str] = None
    while True:
        kwargs: dict[str, Any] = {"userId": "me", "q": query, "maxResults": 500}
        if page_token:
            kwargs["pageToken"] = page_token
        resp = svc.users().messages().list(**kwargs).execute()
        for m in resp.get("messages", []) or []:
            yield m["id"]
        page_token = resp.get("nextPageToken")
        if not page_token:
            return


def _fetch_batch(svc, gmail_ids: list[str]) -> tuple[list[dict], list[tuple[str, str]]]:
    """Fetch full payloads for up to BATCH_SIZE message IDs.

    Returns ``(successful_messages, failed_ids_with_reason)``. Failed
    messages are the caller's problem — we surface the 429/5xx ids so
    the caller can retry them individually with backoff.
    """
    results: list[dict] = []
    failures: list[tuple[str, str]] = []
    idx_to_id = dict(enumerate(gmail_ids))

    def _cb(request_id, response, exception):
        gid = idx_to_id.get(int(request_id), "?")
        if exception is not None:
            reason = "ratelimited" if "429" in str(exception) else "error"
            failures.append((gid, reason))
            return
        results.append(response)

    batch = svc.new_batch_http_request(callback=_cb)
    for i, gid in enumerate(gmail_ids):
        batch.add(
            svc.users().messages().get(userId="me", id=gid, format="full"),
            request_id=str(i),
        )
    batch.execute()
    return results, failures


def _retry_individual(svc, gmail_ids: list[str]) -> tuple[list[dict], list[str]]:
    """Retry a set of message IDs individually with exponential backoff.
    Returns (successfully_fetched, still_failed_ids)."""
    results: list[dict] = []
    still_failed: list[str] = []
    for gid in gmail_ids:
        attempt = 0
        fetched = None
        for backoff in RETRY_BACKOFFS_S:
            time.sleep(backoff)
            try:
                fetched = svc.users().messages().get(
                    userId="me", id=gid, format="full"
                ).execute()
                break
            except HttpError as exc:
                status = getattr(exc.resp, "status", 0)
                attempt += 1
                if status in (429, 500, 503):
                    continue  # retry
                logger.warning("individual retry failed (status=%s) for %s", status, gid)
                break
        if fetched is not None:
            results.append(fetched)
        else:
            still_failed.append(gid)
    return results, still_failed


def _persist_messages(db: Session, mailbox: str, messages: Iterable[dict]) -> int:
    """Insert normalized message dicts (idempotent). Returns count inserted."""
    inserted = 0
    for raw in messages:
        norm = _normalize_message(mailbox, raw)
        if norm is None:
            continue
        cls = classify_email(
            subject=norm.get("subject"),
            body_text=norm.get("body_text") or norm.get("snippet"),
            from_address=norm.get("from_address"),
            labels=norm.get("labels_json"),
        )
        norm["archetype"] = cls.archetype
        norm["topic_tags_json"] = cls.topic_tags
        norm["mentioned_entities_json"] = cls.mentioned_entities
        norm["classified_at"] = datetime.now(timezone.utc)

        existing = db.execute(
            select(EmailMessage).where(EmailMessage.message_id == norm["message_id"])
        ).scalars().first()
        if existing is not None:
            # Refresh classification on already-stored messages? Skip for
            # bulk — re-classify separately if rules change.
            continue
        db.add(EmailMessage(**norm))
        inserted += 1
    db.flush()
    return inserted


def ingest_history(
    db: Session,
    mailbox: str,
    since: date,
    *,
    until: Optional[date] = None,
    chunk_size: int = BATCH_SIZE,
    log_every_n: int = 500,
    max_messages: Optional[int] = None,
) -> dict[str, int]:
    """Bulk historical ingest for a mailbox. Idempotent on re-run — skips
    message IDs already stored.

    Returns stats dict.
    """
    svc = _build_client(mailbox)
    existing = _load_existing_message_ids(db, mailbox)
    logger.info("ingest_history(%s): %d messages already stored", mailbox, len(existing))

    query = f"after:{since.strftime('%Y/%m/%d')}"
    if until:
        query += f" before:{until.strftime('%Y/%m/%d')}"

    stats = {"scanned": 0, "skipped_existing": 0, "fetched": 0, "inserted": 0, "errors": 0}
    chunk: list[str] = []
    start_ts = time.monotonic()

    for gid in _iter_message_ids(svc, query):
        stats["scanned"] += 1
        if max_messages and stats["scanned"] > max_messages:
            break
        probe_id = f"gmail:{gid}"
        if probe_id in existing:
            stats["skipped_existing"] += 1
            continue
        chunk.append(gid)
        if len(chunk) >= chunk_size:
            _drain_chunk(db, svc, mailbox, chunk, existing, stats)
            chunk = []
        if stats["scanned"] % log_every_n == 0:
            rate = stats["inserted"] / max(1, time.monotonic() - start_ts)
            logger.info(
                "  progress: scanned=%d inserted=%d skipped=%d errors=%d  (%.1f ins/s)",
                stats["scanned"], stats["inserted"], stats["skipped_existing"], stats["errors"], rate,
            )

    if chunk:
        _drain_chunk(db, svc, mailbox, chunk, existing, stats)

    _record_sync_state(db, mailbox, status="history_ingested", new_rows=stats["inserted"])
    db.commit()
    logger.info("ingest_history(%s) done: %s", mailbox, stats)
    return stats


def _drain_chunk(
    db: Session,
    svc,
    mailbox: str,
    chunk: list[str],
    existing: set[str],
    stats: dict[str, int],
) -> None:
    try:
        fetched, failures = _fetch_batch(svc, chunk)
    except HttpError as exc:
        logger.warning("batch-level HTTP error: %s; retrying whole chunk", exc)
        time.sleep(5)
        try:
            fetched, failures = _fetch_batch(svc, chunk)
        except Exception:
            logger.exception("batch retry failed; dropping chunk of %d", len(chunk))
            stats["errors"] += len(chunk)
            return
    stats["fetched"] += len(fetched)

    # Retry any per-message failures (429s most common) individually with
    # backoff. Concurrency limits mean bursts fail; serialized retries
    # succeed.
    if failures:
        failed_ids = [gid for gid, _ in failures]
        retried, still_failed = _retry_individual(svc, failed_ids)
        fetched.extend(retried)
        stats["fetched"] += len(retried)
        stats["errors"] += len(still_failed)
        if still_failed:
            logger.warning("%d message(s) still failed after retries: %s",
                           len(still_failed), still_failed[:5])

    inserted = _persist_messages(db, mailbox, fetched)
    stats["inserted"] += inserted
    for m in fetched:
        gid = m.get("id")
        if gid:
            existing.add(f"gmail:{gid}")
    db.commit()
    if INTER_BATCH_SLEEP_S > 0:
        time.sleep(INTER_BATCH_SLEEP_S)


def _record_sync_state(
    db: Session,
    mailbox: str,
    *,
    status: str,
    history_id: Optional[str] = None,
    new_rows: int = 0,
    error: Optional[str] = None,
) -> None:
    state = db.execute(
        select(EmailSyncState).where(EmailSyncState.mailbox == mailbox)
    ).scalars().first()
    if state is None:
        state = EmailSyncState(mailbox=mailbox, total_imported=0)
        db.add(state)
    state.last_sync_at = datetime.now(timezone.utc)
    state.last_sync_status = status
    if history_id is not None:
        state.last_history_id = history_id
    state.last_error = error
    state.total_imported = (state.total_imported or 0) + new_rows


def ingest_incremental(db: Session, mailbox: str) -> dict[str, int]:
    """Incremental sync using the Gmail history API. Falls back to a 30-day
    bulk window if watermark is stale or absent (Gmail only retains history
    for ~7 days, so this is routine for weekly cron cadences)."""
    svc = _build_client(mailbox)
    state = db.execute(
        select(EmailSyncState).where(EmailSyncState.mailbox == mailbox)
    ).scalars().first()

    if not state or not state.last_history_id:
        logger.info("ingest_incremental(%s): no watermark, doing 30-day backfill", mailbox)
        since = date.today().replace(day=1)  # conservative — grabs all of this month
        return ingest_history(db, mailbox, since)

    stats = {"scanned": 0, "inserted": 0, "errors": 0}
    page_token: Optional[str] = None
    new_gids: list[str] = []
    new_history_id: str = state.last_history_id

    try:
        while True:
            kwargs: dict[str, Any] = {
                "userId": "me",
                "startHistoryId": state.last_history_id,
                "historyTypes": ["messageAdded"],
                "maxResults": 500,
            }
            if page_token:
                kwargs["pageToken"] = page_token
            resp = svc.users().history().list(**kwargs).execute()
            new_history_id = resp.get("historyId") or new_history_id
            for h in resp.get("history", []) or []:
                for mod in h.get("messagesAdded", []) or []:
                    gid = (mod.get("message") or {}).get("id")
                    if gid:
                        new_gids.append(gid)
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
    except HttpError as exc:
        if exc.resp.status == 404:  # "historyId not found" — watermark expired
            logger.warning("historyId expired; falling back to 30-day bulk")
            since = date.today().replace(day=1)
            return ingest_history(db, mailbox, since)
        raise

    if new_gids:
        existing = _load_existing_message_ids(db, mailbox)
        for i in range(0, len(new_gids), BATCH_SIZE):
            chunk = new_gids[i : i + BATCH_SIZE]
            _drain_chunk(db, svc, mailbox, chunk, existing, stats)
            stats["scanned"] += len(chunk)

    _record_sync_state(
        db, mailbox, status="incremental_ok",
        history_id=new_history_id, new_rows=stats["inserted"],
    )
    db.commit()
    logger.info("ingest_incremental(%s) done: %s", mailbox, stats)
    return stats
