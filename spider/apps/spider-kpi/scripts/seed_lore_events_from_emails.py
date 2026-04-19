#!/usr/bin/env python3
"""Bulk-seed the lore_events table from the email archive with Opus 4.7.

Phase 1 piece 2 of the company-lore surface. Walks the `email_messages`
table month-by-month, sends batches of subject + snippet rows to
Opus 4.7, and asks it to extract the notable business events that
happened in that month (product launches, firmware rollouts, hardware
revisions, marketing campaigns, outages, press mentions, personnel
changes, major supplier/partner events, holidays with operational
impact).

Key design choices:
  - Month-bucketing because Spider Grills is highly seasonal —
    Memorial Day → July 4 sees 3x winter weeks, so event density is
    uneven. Per-month batches let Opus see "what was happening" in a
    compressed context window.
  - Subject + 160-char snippet only, not full bodies — 40K emails
    would blow token budget. Subject+snippet is enough signal to spot
    real events; the ones that matter get mentioned multiple times.
  - Dedup via the (title, start_date) unique constraint — re-runs are
    safe. source_refs_json captures the message_ids that drove each
    extraction so Joseph can click back to evidence.
  - Opus-extracted events default to confidence='inferred'. Joseph
    upgrades to 'confirmed' via the panel UI when he verifies them.

Usage:
  python3 scripts/seed_lore_events_from_emails.py \
    --since 2023-01-01 --until 2026-04-19 \
    --per-month-sample 400 --dry-run

Flags:
  --since / --until  inclusive date window to extract from
  --per-month-sample max emails per month (default 400; tighter = cheaper)
  --model            Opus model id (default claude-opus-4-7)
  --dry-run          print what would be inserted without writing
  --source-tag       source_type label to use (default 'ai_opus')
  --skip-existing-months  don't re-process a month that already has
                    events with source_type='ai_opus'
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# Allow running from repo root OR scripts/ dir.
SCRIPT_DIR = Path(__file__).resolve().parent
APP_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(APP_ROOT / "backend"))

from sqlalchemy import and_, func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import EmailMessage, LoreEvent  # noqa: E402

logging.basicConfig(
    format="%(asctime)s %(levelname)-8s %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("seed_lore_events")


SYSTEM_PROMPT = """You are the lore archivist for Spider Grills, a smart-grill
company. Your job is to read batches of email subject lines + short snippets
and extract the NOTABLE BUSINESS EVENTS that happened during that time.

A "notable event" is something that would explain an unusual spike, drop, or
pattern on a metrics dashboard. Examples by event_type:
  - launch:            new product or feature goes live
  - incident:          outage, recall, major bug, bad firmware, factory defect
  - campaign:          marketing campaign, influencer push, big promotion
  - promotion:         sitewide sale (Black Friday, Memorial Day, July 4)
  - firmware:          firmware rollout (any version bump)
  - hardware_revision: hardware change (new controller rev, probe redesign)
  - personnel:         hire, departure, restructure at Spider Grills itself
  - press:             media mention, podcast, YouTube review by influencer
  - external:          supply chain, trade show, industry event, tariff change
  - holiday:           operational-impact holiday (Memorial Day, 4th of July)

DO extract events that clearly happened (confidence='inferred') OR that seem
to have happened based on multiple email mentions (confidence='inferred').

DO NOT extract:
  - Routine customer-support tickets or shipping confirmations
  - Ordinary order-confirmation emails
  - Newsletter blasts unless they announce something specific
  - Internal todos, random drafts, or messages without clear events
  - Events that are purely speculative or only referenced once in passing

Prefer FEW high-quality events over many low-confidence ones. Target 3-15
events per month of emails — more only if there's genuinely that much
going on.

For each event:
  - title: <=80 chars, the event in plain English (not a subject line)
  - description: 1-3 sentences of context
  - start_date: YYYY-MM-DD
  - end_date: YYYY-MM-DD or null (single-day or still-open events use null)
  - event_type: one of the types above
  - division: commercial | support | marketing | product_engineering |
              executive | deci | null  (null = company-wide)
  - confidence: 'inferred' for most things you extract; use 'rumored' if
               it's weak signal
  - source_message_ids: the email RFC Message-IDs (<...@...>) that drove
                        this extraction (at least one)

If the batch contains nothing extraction-worthy, return an empty list.
"""


USER_INSTRUCTIONS = """Below are {count} emails from {month_label} at
info@spidergrills.com. Extract notable business events per the system rules.
Return ONLY the events JSON — nothing else.

Emails:
{emails_block}
"""


# ---------------------------------------------------------------------------
# Email sampling
# ---------------------------------------------------------------------------

def iter_month_buckets(start: date, end: date):
    cur = date(start.year, start.month, 1)
    while cur <= end:
        if cur.month == 12:
            nxt = date(cur.year + 1, 1, 1)
        else:
            nxt = date(cur.year, cur.month + 1, 1)
        bucket_end = min(nxt - timedelta(days=1), end)
        bucket_start = max(cur, start)
        yield bucket_start, bucket_end
        cur = nxt


def fetch_month_emails(
    db: Session,
    start: date,
    end: date,
    sample_cap: int,
) -> list[EmailMessage]:
    """Pull up to `sample_cap` emails in [start, end], preferring threads
    that have replies (more likely real events) and longer subjects (less
    likely to be automated receipts)."""
    start_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)

    # Crude noise filter: skip subjects that are obvious automation.
    noise_prefixes = (
        "Order #", "Shipping update", "Your order", "[Shopify]",
        "Out of Office", "Automatic reply", "Undeliverable:",
        "Delivery Status Notification",
    )

    q = (
        select(EmailMessage)
        .where(and_(
            EmailMessage.sent_at >= start_dt,
            EmailMessage.sent_at < end_dt,
            EmailMessage.subject.isnot(None),
        ))
        .order_by(EmailMessage.sent_at.asc())
    )
    rows = db.execute(q).scalars().all()
    filtered = [
        r for r in rows
        if r.subject
        and not any(r.subject.strip().startswith(p) for p in noise_prefixes)
        and len(r.subject.strip()) >= 4
    ]

    # Dedup subjects within a month — many automated replies share subjects.
    seen_subjects: dict[str, EmailMessage] = {}
    for r in filtered:
        key = (r.subject or "").strip().lower()[:140]
        if key not in seen_subjects:
            seen_subjects[key] = r
    deduped = list(seen_subjects.values())

    if len(deduped) <= sample_cap:
        return deduped

    # Even-sample across the month to not bias toward early-month emails.
    step = len(deduped) / sample_cap
    sampled = [deduped[int(i * step)] for i in range(sample_cap)]
    return sampled


def format_email_block(emails: list[EmailMessage]) -> str:
    lines = []
    for e in emails:
        snip = (e.snippet or e.body_preview or "").strip().replace("\n", " ")
        if len(snip) > 160:
            snip = snip[:157] + "..."
        sent = e.sent_at.date().isoformat() if e.sent_at else "unknown"
        fr = (e.from_address or "").strip()[:80]
        mid = e.message_id
        lines.append(f"- [{sent}] <{mid}> FROM {fr}")
        lines.append(f"  SUBJECT: {(e.subject or '').strip()[:200]}")
        if snip:
            lines.append(f"  SNIPPET: {snip}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Claude extraction
# ---------------------------------------------------------------------------

try:
    from pydantic import BaseModel, Field
except ImportError:
    logger.error("pydantic not installed — run inside the backend venv")
    raise


class ExtractedEvent(BaseModel):
    event_type: str
    title: str = Field(..., max_length=256)
    description: Optional[str] = None
    start_date: str  # YYYY-MM-DD
    end_date: Optional[str] = None
    division: Optional[str] = None
    confidence: str = "inferred"
    source_message_ids: list[str] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    events: list[ExtractedEvent] = Field(default_factory=list)


def extract_events_for_month(
    emails: list[EmailMessage],
    month_label: str,
    model: str,
) -> list[ExtractedEvent]:
    if not emails:
        return []
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY missing — cannot run Opus extraction")

    import anthropic

    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        max_retries=2,
        timeout=180.0,
    )

    user_content = USER_INSTRUCTIONS.format(
        count=len(emails),
        month_label=month_label,
        emails_block=format_email_block(emails),
    )

    response = client.messages.parse(
        model=model,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_content}],
        output_format=ExtractionResult,
    )

    parsed = response.parsed_output
    if parsed is None:
        logger.warning("Opus returned no parsed output for %s", month_label)
        return []
    return parsed.events


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------

def upsert_events(
    db: Session,
    extracted: list[ExtractedEvent],
    source_tag: str,
    dry_run: bool,
) -> tuple[int, int]:
    inserted = 0
    skipped = 0
    for ev in extracted:
        try:
            start_d = datetime.strptime(ev.start_date, "%Y-%m-%d").date()
        except ValueError:
            logger.warning("Skipping event with bad start_date: %r", ev.start_date)
            skipped += 1
            continue
        end_d = None
        if ev.end_date:
            try:
                end_d = datetime.strptime(ev.end_date, "%Y-%m-%d").date()
            except ValueError:
                end_d = None

        title = (ev.title or "").strip()[:256]
        if not title:
            skipped += 1
            continue

        # Idempotent: skip if (title, start_date) already exists.
        existing = db.execute(
            select(LoreEvent.id).where(
                and_(LoreEvent.title == title, LoreEvent.start_date == start_d)
            )
        ).first()
        if existing:
            skipped += 1
            continue

        if dry_run:
            logger.info("[dry-run] would insert: %s [%s → %s] type=%s div=%s",
                        title, start_d, end_d, ev.event_type, ev.division)
            inserted += 1
            continue

        row = LoreEvent(
            event_type=(ev.event_type or "other")[:32],
            title=title,
            description=(ev.description or "").strip() or None,
            start_date=start_d,
            end_date=end_d,
            division=(ev.division or None),
            confidence=(ev.confidence or "inferred")[:16],
            source_type=source_tag,
            source_refs_json={"email_message_ids": ev.source_message_ids[:50]},
            metadata_json={"extracted_by": "opus_lore_seed", "model": settings.anthropic_classifier_model},
            created_by="opus_lore_seed",
        )
        db.add(row)
        inserted += 1

    if not dry_run:
        db.commit()
    return inserted, skipped


def month_already_seeded(db: Session, start: date, end: date, source_tag: str) -> bool:
    cnt = db.execute(
        select(func.count(LoreEvent.id)).where(and_(
            LoreEvent.source_type == source_tag,
            LoreEvent.start_date >= start,
            LoreEvent.start_date <= end,
        ))
    ).scalar_one()
    return cnt > 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", required=True, help="YYYY-MM-DD inclusive")
    parser.add_argument("--until", required=True, help="YYYY-MM-DD inclusive")
    parser.add_argument("--per-month-sample", type=int, default=400)
    parser.add_argument("--model", default="claude-opus-4-7")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--source-tag", default="ai_opus")
    parser.add_argument("--skip-existing-months", action="store_true",
                        help="skip months that already have ai_opus events")
    args = parser.parse_args()

    try:
        since = datetime.strptime(args.since, "%Y-%m-%d").date()
        until = datetime.strptime(args.until, "%Y-%m-%d").date()
    except ValueError as exc:
        logger.error("invalid date: %s", exc)
        return 2
    if until < since:
        logger.error("--until must be >= --since")
        return 2

    db = SessionLocal()
    try:
        total_inserted = 0
        total_skipped = 0
        buckets = list(iter_month_buckets(since, until))
        logger.info("Processing %d month buckets from %s to %s", len(buckets), since, until)

        for bucket_start, bucket_end in buckets:
            month_label = bucket_start.strftime("%B %Y")

            if args.skip_existing_months and month_already_seeded(db, bucket_start, bucket_end, args.source_tag):
                logger.info("[%s] skipping — already seeded", month_label)
                continue

            emails = fetch_month_emails(db, bucket_start, bucket_end, args.per_month_sample)
            if not emails:
                logger.info("[%s] no emails in bucket — skip", month_label)
                continue

            logger.info("[%s] extracting events from %d emails via %s",
                        month_label, len(emails), args.model)
            try:
                events = extract_events_for_month(emails, month_label, args.model)
            except Exception as exc:
                logger.exception("[%s] extraction failed: %s", month_label, exc)
                continue

            ins, skp = upsert_events(db, events, args.source_tag, args.dry_run)
            logger.info("[%s] extracted=%d inserted=%d skipped=%d",
                        month_label, len(events), ins, skp)
            total_inserted += ins
            total_skipped += skp

        logger.info("DONE. total_inserted=%d total_skipped=%d dry_run=%s",
                    total_inserted, total_skipped, args.dry_run)
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
