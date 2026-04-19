#!/usr/bin/env python3
"""Gmail archive ingest — historical bulk + incremental.

Pulls messages from one or more Google Workspace shared inboxes via the
Gmail API (service account + domain-wide delegation; see
backend/app/services/gmail_ingest.py for the full design).

Usage:
    # First-run bulk ingest from 2023-01-01 for info@
    python scripts/ingest_email_archive.py --mailbox info@spidergrills.com --since 2023-01-01

    # Cap for smoke-test
    python scripts/ingest_email_archive.py --mailbox info@spidergrills.com --since 2023-01-01 --max 500

    # Daily incremental (reads watermark; 30-day fallback if expired)
    python scripts/ingest_email_archive.py --mailbox info@spidergrills.com --incremental

    # All mailboxes from GMAIL_IMPERSONATE_USERS env var
    python scripts/ingest_email_archive.py --all --since 2023-01-01

Environment:
    GMAIL_SERVICE_ACCOUNT_KEY_PATH  (required) path to service-account JSON
    GMAIL_IMPERSONATE_USERS          comma-separated list of mailbox addresses
    GMAIL_HISTORY_SINCE              default --since value if not overridden
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path


ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def _load_env(p: Path) -> None:
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
            v = v[1:-1]
        os.environ.setdefault(k.strip(), v)


_load_env(ENV_PATH)

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db.session import SessionLocal  # noqa: E402
from app.services.gmail_ingest import ingest_history, ingest_incremental  # noqa: E402


logger = logging.getLogger("ingest_email_archive")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _resolve_mailboxes(args) -> list[str]:
    if args.mailbox:
        return [args.mailbox]
    if args.all:
        raw = os.environ.get("GMAIL_IMPERSONATE_USERS", "").strip()
        boxes = [b.strip() for b in raw.split(",") if b.strip()]
        if not boxes:
            raise SystemExit("--all requested but GMAIL_IMPERSONATE_USERS is empty")
        return boxes
    raise SystemExit("must specify --mailbox <address> or --all")


def main() -> int:
    default_since = os.environ.get("GMAIL_HISTORY_SINCE", "2023-01-01")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mailbox", type=str, default=None, help="single mailbox to ingest")
    p.add_argument("--all", action="store_true", help="ingest every mailbox in GMAIL_IMPERSONATE_USERS")
    p.add_argument("--since", type=_parse_date, default=_parse_date(default_since),
                   help=f"start date for bulk ingest (default: {default_since})")
    p.add_argument("--until", type=_parse_date, default=None, help="optional end date")
    p.add_argument("--incremental", action="store_true",
                   help="incremental sync via Gmail history watermark (daily cadence)")
    p.add_argument("--max", type=int, default=None, help="cap scanned messages (smoke test)")
    args = p.parse_args()

    mailboxes = _resolve_mailboxes(args)
    logger.info("ingest target(s): %s", ", ".join(mailboxes))

    total_errors = 0
    with SessionLocal() as db:
        for mbox in mailboxes:
            try:
                if args.incremental:
                    ingest_incremental(db, mbox)
                else:
                    ingest_history(
                        db, mbox,
                        since=args.since,
                        until=args.until,
                        max_messages=args.max,
                    )
            except Exception:
                logger.exception("mailbox %s failed", mbox)
                total_errors += 1

    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
