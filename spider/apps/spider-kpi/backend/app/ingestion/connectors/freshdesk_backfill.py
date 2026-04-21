"""Full-archive Freshdesk backfill: descriptions + conversations for every ticket.

Run once per environment to pull the full historical archive into the KB.
Idempotent — can be re-run; skips tickets whose conversations were already
fetched unless ``--force-conversations`` is passed.

Usage (on droplet):
    cd /opt/spiderclawkpi/spider/apps/spider-kpi/backend
    ../.venv/bin/python -m app.ingestion.connectors.freshdesk_backfill --since-days 1825

The default ``--since-days`` (5 years) covers everything in our Freshdesk
archive (~9,400 tickets from 2023 onward). List pagination uses
``include=stats,description`` so descriptions land in one request per 100
tickets. Conversations are fetched per-ticket via
``/tickets/{id}/conversations``. Rate-limit-aware: sleeps on 429 and
paces requests to stay under ~100/min.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.ingestion.connectors.freshdesk import (
    _auth,
    _base_url,
    _request_conversations,
    _upsert_conversations,
)
from app.models import FreshdeskTicket, FreshdeskTicketConversation


logger = logging.getLogger("freshdesk_backfill")
if not logger.handlers:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


PACE_DELAY_SECONDS = 0.6  # ~100 req/min ceiling
RATE_LIMIT_SLEEP_SECONDS = 60


def _sleep_for_rate_limit(response: requests.Response) -> None:
    """Sleep long enough to recover from a 429."""
    retry_after = response.headers.get("Retry-After")
    try:
        wait = int(retry_after) if retry_after else RATE_LIMIT_SLEEP_SECONDS
    except ValueError:
        wait = RATE_LIMIT_SLEEP_SECONDS
    logger.warning("rate-limited, sleeping %ss", wait)
    time.sleep(wait)


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _extract_first_response_hours(ticket: dict[str, Any]) -> float:
    stats = ticket.get("stats") or {}
    for key in ["first_responded_at", "first_response_time_in_seconds", "first_response_time"]:
        value = stats.get(key)
        if isinstance(value, (int, float)):
            if "seconds" in key:
                return float(value) / 3600.0
            return float(value)
    return 0.0


def _upsert_ticket(db: Session, ticket: dict[str, Any]) -> tuple[str, bool]:
    ticket_id = str(ticket.get("id"))
    created_at = _parse_iso(ticket.get("created_at"))
    updated_at = _parse_iso(ticket.get("updated_at"))
    resolved_at = _parse_iso(ticket.get("resolved_at"))

    record = db.execute(
        select(FreshdeskTicket).where(FreshdeskTicket.ticket_id == ticket_id)
    ).scalars().first()
    inserted = record is None
    if inserted:
        record = FreshdeskTicket(ticket_id=ticket_id)
        db.add(record)

    status = str(ticket.get("status_name") or ticket.get("status") or "unknown")
    record.subject = ticket.get("subject")
    record.status = status
    record.priority = str(ticket.get("priority") or "unknown")
    record.channel = str(ticket.get("source") or "unknown")
    record.group_name = str(ticket.get("group_id") or "unassigned")
    record.requester_id = str(ticket.get("requester_id") or "") or None
    record.agent_id = str(ticket.get("responder_id") or "unassigned")
    record.created_at_source = created_at
    record.updated_at_source = updated_at
    record.resolved_at_source = resolved_at
    record.first_response_hours = _extract_first_response_hours(ticket)
    record.resolution_hours = (
        (resolved_at - created_at).total_seconds() / 3600.0
        if (resolved_at and created_at)
        else 0.0
    )
    csat = float((ticket.get("satisfaction_rating") or {}).get("score") or 0.0)
    record.csat_score = csat if csat > 0 else None
    record.tags_json = ticket.get("tags") or []
    record.category = (ticket.get("tags") or [None])[0]
    record.raw_payload = ticket
    record.description_text = ticket.get("description_text")
    record.description_html = ticket.get("description")
    record.description_fetched_at = datetime.now(timezone.utc)
    return ticket_id, inserted


def backfill_tickets(db: Session, since_days: int) -> dict[str, int]:
    """Paginate through /tickets with include=description; upsert each."""
    base_url = _base_url()
    auth = _auth()
    since = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    page = 1
    inserted = 0
    updated = 0
    while True:
        params = {
            "updated_since": since,
            "per_page": 100,
            "page": page,
            "include": "stats,description",
            "order_by": "updated_at",
            "order_type": "desc",
        }
        resp = requests.get(f"{base_url}/tickets", auth=auth, params=params, timeout=45)
        if resp.status_code == 429:
            _sleep_for_rate_limit(resp)
            continue
        resp.raise_for_status()
        batch = resp.json() or []
        if not batch:
            break
        for ticket in batch:
            _, was_inserted = _upsert_ticket(db, ticket)
            if was_inserted:
                inserted += 1
            else:
                updated += 1
        db.commit()
        logger.info("tickets page %s processed (+%s new, %s total so far)", page, len(batch), inserted + updated)
        if len(batch) < 100:
            break
        page += 1
        time.sleep(PACE_DELAY_SECONDS)
    return {"inserted": inserted, "updated": updated}


def backfill_conversations(db: Session, force: bool = False) -> dict[str, int]:
    """For each ticket missing conversations_fetched_at, pull conversations."""
    base_url = _base_url()
    q = select(FreshdeskTicket.ticket_id)
    if not force:
        q = q.where(FreshdeskTicket.conversations_fetched_at.is_(None))
    q = q.order_by(FreshdeskTicket.updated_at_source.desc().nullslast())
    ticket_ids = [row[0] for row in db.execute(q).all()]

    total = len(ticket_ids)
    logger.info("fetching conversations for %s tickets", total)
    fetched = 0
    new_conv_rows = 0
    errored = 0
    for i, ticket_id in enumerate(ticket_ids, 1):
        try:
            resp = _request_conversations(base_url, ticket_id)
            while resp.status_code == 429:
                _sleep_for_rate_limit(resp)
                resp = _request_conversations(base_url, ticket_id)
            if not resp.ok:
                logger.warning("conversations %s failed %s", ticket_id, resp.status_code)
                errored += 1
                continue
            conversations = resp.json() or []
            new_conv_rows += _upsert_conversations(db, ticket_id, conversations)
            record = db.execute(
                select(FreshdeskTicket).where(FreshdeskTicket.ticket_id == ticket_id)
            ).scalars().first()
            if record is not None:
                record.conversations_fetched_at = datetime.now(timezone.utc)
            fetched += 1
        except Exception:
            logger.exception("conversations %s errored", ticket_id)
            errored += 1

        if i % 50 == 0:
            db.commit()
            logger.info("  %s / %s tickets fetched (+%s conv rows so far, %s errors)", i, total, new_conv_rows, errored)

        time.sleep(PACE_DELAY_SECONDS)

    db.commit()
    logger.info("done: fetched=%s new_conv_rows=%s errored=%s", fetched, new_conv_rows, errored)
    return {"tickets_fetched": fetched, "conversation_rows": new_conv_rows, "errored": errored}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since-days", type=int, default=1825, help="Days of history to pull (default 5 years)")
    parser.add_argument("--skip-tickets", action="store_true", help="Skip ticket list pagination (conversations only)")
    parser.add_argument("--skip-conversations", action="store_true", help="Skip conversations (tickets only)")
    parser.add_argument("--force-conversations", action="store_true", help="Re-fetch conversations for already-fetched tickets")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if not args.skip_tickets:
            logger.info("=== Phase 1: tickets + descriptions ===")
            t_stats = backfill_tickets(db, since_days=args.since_days)
            logger.info("ticket phase: %s", t_stats)
        else:
            logger.info("skipping ticket phase")
        total_tickets = db.execute(select(func.count(FreshdeskTicket.id))).scalar() or 0
        with_desc = db.execute(select(func.count(FreshdeskTicket.id)).where(FreshdeskTicket.description_text.is_not(None))).scalar() or 0
        logger.info("tickets in db: %s (with description: %s)", total_tickets, with_desc)

        if not args.skip_conversations:
            logger.info("=== Phase 2: conversations ===")
            c_stats = backfill_conversations(db, force=args.force_conversations)
            logger.info("conversation phase: %s", c_stats)
        else:
            logger.info("skipping conversation phase")

        total_conv = db.execute(select(func.count(FreshdeskTicketConversation.id))).scalar() or 0
        logger.info("conversation rows in db: %s", total_conv)
    finally:
        db.close()


if __name__ == "__main__":
    main()
