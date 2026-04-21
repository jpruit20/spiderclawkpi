"""One-time retroactive close of the pre-cutover Freshdesk backlog.

Context: on the CX_CUTOVER_DATE (2026-05-01) the team resets to a new
operating model — closing tickets, following SLA, tagging properly. The
pre-cutover "open backlog" is a ghost: ~9,000 tickets that are closed in
reality but never clicked Resolved because nobody knew they had to.
Leaving them open would drag every operational KPI underwater on day
one.

This script bulk-closes pre-cutover tickets that are:
  * created before the cutover date
  * still status=open or pending
  * last customer activity >= IDLE_DAYS ago (default 30)

Freshdesk auto-reopens a ticket when the customer replies, so this is
safe: any genuinely-active conversation will bounce back to the queue.

USAGE (on the droplet):

    # Dry run — lists what would change, makes no API calls.
    python -m scripts.cx_cutover_retroactive_close --dry-run

    # Live run — actually closes tickets.
    python -m scripts.cx_cutover_retroactive_close --execute

    # Narrow by idle window (e.g. be conservative, only close >=60d idle):
    python -m scripts.cx_cutover_retroactive_close --dry-run --idle-days 60

    # Limit for smoke-test:
    python -m scripts.cx_cutover_retroactive_close --execute --limit 20

On success, every touched ticket gets a private note:

    "Auto-closed during {CUTOVER} CX operations reset — no customer
     activity in >{IDLE_DAYS} days. Ticket will auto-reopen if the
     customer replies. See internal CX cutover memo."
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Make the backend package importable when this file is invoked as a script.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import requests  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.ingestion.connectors.freshdesk import (  # noqa: E402
    _auth,
    normalize_freshdesk_base_url,
)
from app.models import FreshdeskTicket  # noqa: E402

logger = logging.getLogger("cx_cutover")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# Freshdesk ticket status codes — see Freshdesk API reference.
STATUS_OPEN = 2
STATUS_PENDING = 3
STATUS_CLOSED = 5

OPEN_STATUS_TEXT_TOKENS = ("open", "pending", "waiting", "on hold")


def _is_pre_cutover_open(ticket: FreshdeskTicket, cutover: date) -> bool:
    if not ticket.created_at_source:
        return False
    if ticket.created_at_source.date() >= cutover:
        return False
    if ticket.resolved_at_source is not None:
        return False
    status_text = (ticket.status or "").lower()
    if not status_text:
        # No status text recorded — fall back to resolved-at heuristic above.
        return True
    return any(token in status_text for token in OPEN_STATUS_TEXT_TOKENS)


def _last_activity(ticket: FreshdeskTicket) -> datetime | None:
    # Prefer the updated_at from the source; fall back to created_at.
    return ticket.updated_at_source or ticket.created_at_source


def _close_ticket(base_url: str, ticket_id: str, note: str) -> tuple[bool, str]:
    """Add a private note + flip status to Closed. Returns (ok, detail)."""
    auth = _auth()
    headers = {"Content-Type": "application/json"}

    # Step 1: add private note so the audit trail captures the reason.
    note_url = f"{base_url}/tickets/{ticket_id}/notes"
    try:
        r = requests.post(
            note_url,
            auth=auth,
            headers=headers,
            json={"body": note, "private": True},
            timeout=30,
        )
    except requests.RequestException as exc:
        return False, f"note request failed: {exc}"
    if r.status_code >= 400:
        return False, f"note HTTP {r.status_code}: {r.text[:200]}"

    # Step 2: PUT the ticket with status=5 (Closed).
    ticket_url = f"{base_url}/tickets/{ticket_id}"
    try:
        r = requests.put(
            ticket_url,
            auth=auth,
            headers=headers,
            json={"status": STATUS_CLOSED},
            timeout=30,
        )
    except requests.RequestException as exc:
        return False, f"close request failed: {exc}"
    if r.status_code >= 400:
        return False, f"close HTTP {r.status_code}: {r.text[:200]}"

    return True, "closed"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Retroactive-close pre-cutover Freshdesk backlog.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change; make no API calls. (default)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually close the tickets via Freshdesk API.",
    )
    parser.add_argument(
        "--idle-days",
        type=int,
        default=30,
        help="Only close tickets with last activity >= this many days ago.",
    )
    parser.add_argument(
        "--cutover",
        type=str,
        default=None,
        help="Override cutover date (YYYY-MM-DD). Defaults to settings.cx_cutover_date.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max tickets to touch (0 = no limit). Use a small number for smoke-tests.",
    )
    parser.add_argument(
        "--sleep-ms",
        type=int,
        default=200,
        help="Delay between API calls to stay under Freshdesk rate limits.",
    )
    args = parser.parse_args()

    if args.dry_run and args.execute:
        logger.error("--dry-run and --execute are mutually exclusive.")
        return 2
    execute = args.execute  # default: dry-run unless --execute
    if not execute:
        logger.info("DRY RUN — no Freshdesk writes will be performed. Pass --execute to run for real.")

    settings = get_settings()
    cutover_raw = args.cutover or settings.cx_cutover_date
    try:
        cutover = date.fromisoformat((cutover_raw or "").strip())
    except ValueError:
        logger.error("Invalid cutover date %r — set CX_CUTOVER_DATE or pass --cutover YYYY-MM-DD.", cutover_raw)
        return 2
    logger.info("Cutover date: %s", cutover.isoformat())
    logger.info("Idle threshold: >= %d days", args.idle_days)

    if execute:
        if not settings.freshdesk_domain or not settings.freshdesk_api_key:
            logger.error("Freshdesk credentials missing; cannot execute.")
            return 2
        base_url = normalize_freshdesk_base_url(settings.freshdesk_domain)
    else:
        base_url = ""  # unused in dry-run

    now = datetime.now(timezone.utc)
    idle_cutoff = now - timedelta(days=args.idle_days)
    note = (
        f"Auto-closed during {cutover.isoformat()} CX operations reset — "
        f"no customer activity in >{args.idle_days} days. Ticket will "
        "auto-reopen if the customer replies. See internal CX cutover memo."
    )

    with SessionLocal() as session:
        tickets: list[FreshdeskTicket] = list(session.execute(
            select(FreshdeskTicket).where(
                FreshdeskTicket.created_at_source < datetime.combine(cutover, datetime.min.time(), tzinfo=timezone.utc),
                FreshdeskTicket.resolved_at_source.is_(None),
            ).order_by(FreshdeskTicket.updated_at_source.asc())
        ).scalars())

    logger.info("Pulled %d candidates from DB (pre-cutover + unresolved).", len(tickets))

    targets: list[FreshdeskTicket] = []
    skipped_not_open = 0
    skipped_not_idle = 0
    for t in tickets:
        if not _is_pre_cutover_open(t, cutover):
            skipped_not_open += 1
            continue
        activity = _last_activity(t)
        if activity is None or activity > idle_cutoff:
            skipped_not_idle += 1
            continue
        targets.append(t)
        if args.limit and len(targets) >= args.limit:
            break

    logger.info(
        "Shortlist: %d tickets to close. Skipped: not-open=%d, not-idle=%d.",
        len(targets), skipped_not_open, skipped_not_idle,
    )

    if not execute:
        for t in targets[:20]:
            logger.info(
                "  would close: #%s status=%r updated=%s subject=%r",
                t.ticket_id, t.status, t.updated_at_source, (t.subject or "")[:60],
            )
        if len(targets) > 20:
            logger.info("  ... and %d more.", len(targets) - 20)
        logger.info("DRY RUN complete. Pass --execute to apply.")
        return 0

    ok = 0
    failed = 0
    for i, t in enumerate(targets, start=1):
        success, detail = _close_ticket(base_url, t.ticket_id, note)
        if success:
            ok += 1
        else:
            failed += 1
            logger.warning("close #%s failed: %s", t.ticket_id, detail)
        if i % 25 == 0:
            logger.info("progress: %d / %d (ok=%d failed=%d)", i, len(targets), ok, failed)
        if args.sleep_ms > 0:
            time.sleep(args.sleep_ms / 1000.0)

    logger.info("Done. closed=%d failed=%d total_targets=%d", ok, failed, len(targets))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
