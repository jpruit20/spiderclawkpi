"""KPI inbox connector — twice-daily IMAP poll for vendor invoice ingestion.

Architecture
------------

Joseph set up ``kpi@spidergrills.ai`` (Cloudflare Email Routing) →
forwarded to a dedicated Gmail account that the dashboard polls via
IMAP. Senders we route mail INTO this inbox (FedEx FBO weekly CSV
exports first, future LTL carriers later) get parsed and ingested by
sender-pattern-matched handlers.

Data flow:

  IMAP UNSEEN search
     ↓
  for each message:
     ↓
     decode headers (subject, from, to, date)
     ↓
     check Message-ID against processed_emails ledger → skip if seen
     ↓
     extract attachments
     ↓
     match (from, subject) against PARSERS registry → first match wins
     ↓
     run parser; persist records (parser-specific destination tables)
     ↓
     write ledger row with status / records_created
     ↓
     mark message \\Seen on the server (so future UNSEEN polls skip it)

Idempotency
-----------

Message-ID is the natural key. Re-poll is safe — every message either
has a ledger row already (skip) or doesn't (process). The mark-read
step happens AFTER the ledger commit so a crash mid-process leaves
the message UNSEEN and we'll retry on the next poll.

Why not also walk SEEN messages
-------------------------------

Once we've processed a message it's marked \\Seen. The next poll's
UNSEEN search naturally excludes it. If a human reads a message in
the Gmail web UI before our poll fires, that message gets marked
\\Seen too — and we'll skip it. That's the right tradeoff: the
inbox is operationally for the dashboard, and a human glancing at a
welcome email shouldn't trigger an ingestion attempt anyway.
"""
from __future__ import annotations

import email
import email.utils
import imaplib
import io
import json
import logging
import re
from datetime import datetime, timezone
from email.header import decode_header
from email.message import Message
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings


logger = logging.getLogger(__name__)
settings = get_settings()


# ── Parser registry ──────────────────────────────────────────────────
#
# A parser is a callable invoked with (db, message, attachments) and
# must return ``{"records_created": int, "extra": dict}``. Parsers
# write to whatever destination tables are appropriate for their data
# (e.g. fedex_invoice_charges) — the connector itself only cares
# about the count for the ledger row.
#
# Registration order matters: first match wins. Put more specific
# patterns above more general ones.

ParserFn = Callable[[Session, Message, list[dict[str, Any]]], dict[str, Any]]
ParserEntry = tuple[str, str, str, ParserFn]  # (name, sender_re, subject_re, fn)
PARSERS: list[ParserEntry] = []


def register_parser(name: str, sender_re: str, subject_re: str, fn: ParserFn) -> None:
    PARSERS.append((name, sender_re, subject_re, fn))


# ── helpers ──────────────────────────────────────────────────────────


class KpiInboxConfigError(RuntimeError):
    pass


def _decode_header(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        parts = decode_header(value)
    except Exception:
        return str(value)
    out: list[str] = []
    for text, charset in parts:
        if isinstance(text, bytes):
            try:
                out.append(text.decode(charset or "utf-8", errors="replace"))
            except (LookupError, TypeError):
                out.append(text.decode("utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


def _parse_address(value: Optional[str]) -> str:
    if not value:
        return ""
    _, addr = email.utils.parseaddr(_decode_header(value))
    return (addr or "").lower()


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    # Ensure tz-aware; some senders omit timezone.
    if dt and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _extract_attachments(msg: Message) -> list[dict[str, Any]]:
    """Walk the MIME tree and return attachment-like parts.

    Returns a list of ``{filename, content_type, content_bytes, size}``.
    Treats both ``attachment`` and ``inline`` Content-Dispositions as
    candidates as long as they have a filename — some senders (FedEx
    in particular) attach CSVs as ``inline``.
    """
    attachments: list[dict[str, Any]] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        cd = (part.get("Content-Disposition") or "").lower()
        if "attachment" not in cd and "inline" not in cd:
            continue
        filename = part.get_filename()
        if not filename:
            continue
        filename = _decode_header(filename)
        try:
            payload = part.get_payload(decode=True) or b""
        except Exception:
            payload = b""
        attachments.append({
            "filename": filename,
            "content_type": (part.get_content_type() or "").lower(),
            "content_bytes": payload,
            "size": len(payload),
        })
    return attachments


def _select_parser(from_addr: str, subject: str) -> Optional[tuple[str, ParserFn]]:
    for name, sender_re, subject_re, fn in PARSERS:
        if re.search(sender_re, from_addr or "", re.IGNORECASE) and re.search(
            subject_re, subject or "", re.IGNORECASE
        ):
            return name, fn
    return None


def _require_creds() -> tuple[str, int, str, str]:
    if not all([settings.kpi_inbox_host, settings.kpi_inbox_user, settings.kpi_inbox_password]):
        raise KpiInboxConfigError(
            "KPI_INBOX_HOST / KPI_INBOX_USER / KPI_INBOX_PASSWORD must all be set in the env. "
            "See the kpi_inbox connector docstring for setup."
        )
    return (
        str(settings.kpi_inbox_host),
        int(settings.kpi_inbox_port),
        str(settings.kpi_inbox_user),
        str(settings.kpi_inbox_password),
    )


# ── poll ──────────────────────────────────────────────────────────────


def poll_inbox(db: Session, *, mailbox: str = "INBOX", max_messages: int = 100) -> dict[str, Any]:
    """Fetch UNSEEN messages, route through the parser registry,
    persist a ledger row per message, mark each \\Seen on success.

    Returns counters: messages_fetched, messages_processed,
    messages_no_match, messages_already_seen, messages_errored,
    records_created_total, duration_ms.
    """
    # Local import to avoid a circular at module load (the model needs
    # Base, which pulls in everything else).
    from app.models import ProcessedEmail

    host, port, user, pwd = _require_creds()
    started = datetime.now(timezone.utc)
    counts = {
        "messages_fetched": 0,
        "messages_processed": 0,
        "messages_no_match": 0,
        "messages_already_seen": 0,
        "messages_errored": 0,
        "records_created_total": 0,
    }

    mail = imaplib.IMAP4_SSL(host, port)
    try:
        typ, resp = mail.login(user, pwd)
        if typ != "OK":
            raise KpiInboxConfigError(f"IMAP login failed: {typ} {resp}")
        mail.select(mailbox)
        typ, data = mail.search(None, "UNSEEN")
        if typ != "OK" or not data or not data[0]:
            counts["duration_ms"] = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
            return counts

        ids = data[0].split()[:max_messages]
        counts["messages_fetched"] = len(ids)

        for raw_id in ids:
            try:
                typ, msg_data = mail.fetch(raw_id, "(RFC822)")
            except imaplib.IMAP4.error as exc:
                logger.warning("kpi_inbox: fetch error on uid=%s: %s", raw_id, exc)
                continue
            if typ != "OK" or not msg_data:
                continue
            raw = next((p[1] for p in msg_data if isinstance(p, tuple)), None)
            if not raw:
                continue
            msg = email.message_from_bytes(raw)

            message_id = (msg.get("Message-ID") or msg.get("Message-Id") or "").strip()
            if not message_id:
                # Synthesize a stable-ish id from the raw bytes hash so the
                # ledger still has SOMETHING unique. Better than dropping
                # the row and re-processing forever.
                message_id = f"<no-msg-id:{hash(raw)}@spidergrills.ai>"

            # Skip if already seen (idempotent re-poll)
            existing = db.execute(
                select(ProcessedEmail).where(ProcessedEmail.message_id == message_id)
            ).scalar_one_or_none()
            if existing:
                counts["messages_already_seen"] += 1
                # Mark seen so future UNSEEN searches skip it cleanly.
                try:
                    mail.store(raw_id, "+FLAGS", "\\Seen")
                except imaplib.IMAP4.error:
                    pass
                continue

            subject = _decode_header(msg.get("Subject"))
            from_addr = _parse_address(msg.get("From"))
            to_addr = _parse_address(msg.get("To"))
            received_at = _parse_date(msg.get("Date"))
            attachments = _extract_attachments(msg)

            ledger = ProcessedEmail(
                message_id=message_id[:1024],
                gmail_uid=int(raw_id) if raw_id.isdigit() else None,
                mailbox=mailbox,
                subject=subject[:2000] if subject else None,
                from_addr=from_addr[:512] if from_addr else None,
                to_addr=to_addr[:512] if to_addr else None,
                received_at=received_at,
                attachment_count=len(attachments),
                raw_headers_json={
                    "message_id": message_id,
                    "from": from_addr,
                    "to": to_addr,
                    "subject": subject,
                    "date": msg.get("Date"),
                    "attachment_filenames": [a["filename"] for a in attachments],
                },
                status="processed",  # placeholder, overwritten below
                records_created=0,
            )

            parser_match = _select_parser(from_addr, subject)
            if not parser_match:
                ledger.parser_used = "no_match"
                ledger.status = "no_match"
                counts["messages_no_match"] += 1
                logger.info(
                    "kpi_inbox: no_match from=%s subject=%r attachments=%d",
                    from_addr, (subject or "")[:80], len(attachments),
                )
            else:
                parser_name, parser_fn = parser_match
                ledger.parser_used = parser_name
                try:
                    result = parser_fn(db, msg, attachments)
                    ledger.status = "processed"
                    ledger.records_created = int(result.get("records_created", 0))
                    counts["messages_processed"] += 1
                    counts["records_created_total"] += ledger.records_created
                    logger.info(
                        "kpi_inbox: parser=%s from=%s records=%d",
                        parser_name, from_addr, ledger.records_created,
                    )
                except Exception as exc:
                    logger.exception(
                        "kpi_inbox: parser=%s failed on message_id=%s",
                        parser_name, message_id,
                    )
                    ledger.status = "error"
                    ledger.error_message = str(exc)[:2000]
                    counts["messages_errored"] += 1
                    # Roll back any partial parser writes; ledger row
                    # still goes through in its own transaction below.
                    db.rollback()

            db.add(ledger)
            try:
                db.commit()
            except Exception:
                logger.exception("kpi_inbox: ledger insert failed for message_id=%s", message_id)
                db.rollback()
                # Don't mark \\Seen; we'll retry next poll.
                continue

            # Mark seen ONLY after the ledger commit lands. If we crash
            # before this line the message stays UNSEEN and we'll
            # re-encounter it next poll — the ledger uniqueness on
            # message_id makes that retry a no-op.
            try:
                mail.store(raw_id, "+FLAGS", "\\Seen")
            except imaplib.IMAP4.error as exc:
                logger.warning("kpi_inbox: failed to mark seen uid=%s: %s", raw_id, exc)

    finally:
        try:
            mail.logout()
        except Exception:
            pass

    counts["duration_ms"] = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    logger.info("kpi_inbox.poll: %s", counts)
    return counts


def register_source(db: Session) -> None:
    """Upsert the source_config row so System Health surfaces this connector.

    Idempotent. Called from the admin debug endpoint and on first
    scheduler run so the row exists before any ingest runs.
    """
    from app.services.source_health import upsert_source_config

    configured = bool(
        settings.kpi_inbox_host and settings.kpi_inbox_user and settings.kpi_inbox_password
    )
    upsert_source_config(
        db,
        "kpi_inbox",
        configured=configured,
        sync_mode="poll",
        config_json={
            "host": settings.kpi_inbox_host,
            "user_set": bool(settings.kpi_inbox_user),
        },
    )


def health_check() -> dict[str, Any]:
    """Confirm IMAP credentials work + report inbox metadata.

    Performs a login, lists mailboxes, counts INBOX messages, and
    logs out. No messages are read or modified. Used by the admin
    debug endpoint and the weekly health audit.
    """
    if not all([settings.kpi_inbox_host, settings.kpi_inbox_user, settings.kpi_inbox_password]):
        return {
            "status": "unconfigured",
            "host": settings.kpi_inbox_host,
            "message": "KPI_INBOX_* env vars not all set",
        }
    try:
        host, port, user, pwd = _require_creds()
        mail = imaplib.IMAP4_SSL(host, port)
        try:
            typ, _ = mail.login(user, pwd)
            if typ != "OK":
                return {"status": "error", "host": host, "message": "IMAP login returned non-OK"}
            mail.select("INBOX")
            typ, ids = mail.search(None, "ALL")
            inbox_count = len(ids[0].split()) if (typ == "OK" and ids and ids[0]) else 0
            typ, unseen = mail.search(None, "UNSEEN")
            unseen_count = len(unseen[0].split()) if (typ == "OK" and unseen and unseen[0]) else 0
            return {
                "status": "healthy",
                "host": host,
                "user": user,
                "inbox_total": inbox_count,
                "inbox_unseen": unseen_count,
            }
        finally:
            try:
                mail.logout()
            except Exception:
                pass
    except Exception as exc:
        return {"status": "error", "host": settings.kpi_inbox_host, "message": f"{type(exc).__name__}: {exc}"}


# ── Parsers ──────────────────────────────────────────────────────────


def _expand_csv_payloads(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Walk attachments, returning a flat list of CSV payloads.

    Handles three packaging shapes FedEx FBO uses depending on report
    size and account config:
      * Direct .csv / text-csv attachment — return as-is.
      * .zip archive — extract every CSV inside (ignores other entries).
      * Multiple CSVs in one ZIP — yield one payload per extracted CSV.

    Each payload is ``{filename, content_bytes}`` regardless of source
    shape, so the parser body can stay flat.
    """
    import zipfile

    out: list[dict[str, Any]] = []
    for att in attachments:
        name = att["filename"].lower()
        ctype = att["content_type"]
        if name.endswith(".csv") or "csv" in ctype:
            out.append({"filename": att["filename"], "content_bytes": att["content_bytes"]})
            continue
        if name.endswith(".zip") or "zip" in ctype or ctype == "application/x-zip-compressed":
            try:
                zf = zipfile.ZipFile(io.BytesIO(att["content_bytes"]))
            except zipfile.BadZipFile:
                logger.warning("kpi_inbox.fedex: bad zip archive %s", att["filename"])
                continue
            for member in zf.namelist():
                if not member.lower().endswith(".csv"):
                    continue
                try:
                    inner = zf.read(member)
                except (KeyError, zipfile.BadZipFile) as exc:
                    logger.warning("kpi_inbox.fedex: could not read %s from %s: %s", member, att["filename"], exc)
                    continue
                out.append({
                    # Preserve the parent zip name in the filename for
                    # provenance (raw_payload.filename gets the combined
                    # path, useful when the same zip carries multiple CSVs).
                    "filename": f"{att['filename']}::{member}",
                    "content_bytes": inner,
                })
            continue
        # Other types (PDF, XML, etc.) — log and skip
        logger.debug(
            "kpi_inbox.fedex: skipping non-CSV/non-ZIP attachment %s (type=%s)",
            att["filename"], ctype,
        )
    return out


def _parse_fedex_invoice(
    db: Session, msg: Message, attachments: list[dict[str, Any]]
) -> dict[str, Any]:
    """Parse a FedEx Billing Online invoice CSV into fedex_invoice_charges.

    Capture-first strategy: until the first real CSV arrives we don't
    know FedEx's exact column names (they vary by report flavor and
    account region). Rather than guess, this parser:

      1. Expands each attachment via _expand_csv_payloads (handles raw
         CSV, single ZIP, multi-CSV ZIP).
      2. Decodes (UTF-8 with BOM tolerance, falls back to latin-1).
      3. Iterates rows via csv.DictReader.
      4. For each row, writes a fedex_invoice_charges entry with
         charge_category='UNPARSED' and the full row preserved in
         raw_payload. Required columns get defaulted to safe values.
      5. Logs sample column names so a refinement pass can swap in
         the real schema after a real invoice lands.

    Once a real invoice arrives, swap the body for a precise mapping;
    re-running this parser via the admin manual-trigger route is safe
    because the unique constraint on (invoice_number, tracking_number,
    charge_category) prevents duplicates.
    """
    from app.models import FedexInvoiceCharge
    import csv

    csv_payloads = _expand_csv_payloads(attachments)
    if not csv_payloads:
        logger.info(
            "kpi_inbox.fedex: no CSV/ZIP attachment in message subject=%r (%d attachments)",
            msg.get("Subject"), len(attachments),
        )
        return {"records_created": 0}

    inserted = 0
    for payload in csv_payloads:
        raw = payload["content_bytes"]
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1", errors="replace")

        # csv.Sniffer can guess the delimiter; default to comma if it can't
        try:
            dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        if not reader.fieldnames:
            logger.warning("kpi_inbox.fedex: CSV %s has no header", payload["filename"])
            continue
        logger.info(
            "kpi_inbox.fedex: parsing %s columns_count=%d sample_columns=%s",
            payload["filename"], len(reader.fieldnames), list(reader.fieldnames)[:10],
        )

        for row_idx, row in enumerate(reader):
            # Synthetic invoice_number / tracking_number until we know
            # which columns hold them. Once we do, swap to row[<col>].
            synth_invoice = (
                row.get("Invoice Number") or row.get("InvoiceNumber") or row.get("invoice_number")
                or f"unparsed-{payload['filename']}"
            )[:64]
            synth_tracking = (
                row.get("Tracking Number") or row.get("TrackingNumber")
                or row.get("Tracking #") or row.get("tracking_number")
                or f"unparsed-{payload['filename']}-{row_idx}"
            )[:64]
            try:
                charge_amount = float(
                    (row.get("Total Charges") or row.get("TotalCharges")
                     or row.get("Net Charge") or row.get("Amount") or "0").replace(",", "").replace("$", "")
                )
            except (TypeError, ValueError):
                charge_amount = 0.0

            charge = FedexInvoiceCharge(
                invoice_number=synth_invoice,
                invoice_currency="USD",
                tracking_number=synth_tracking,
                is_spider=True,  # everything in this inbox is Spider's by definition
                charge_category="UNPARSED",
                charge_description="Captured prior to parser refinement; see raw_payload",
                charge_amount_usd=charge_amount,
                raw_payload={
                    "filename": payload["filename"],
                    "row_index": row_idx,
                    "row": row,
                },
            )
            db.add(charge)
            inserted += 1

    return {"records_created": inserted, "extra": {"csv_payloads_seen": len(csv_payloads)}}


# Registration order = priority (first match wins).
#
# Sender regex accepts both:
#   * direct FedEx senders (when FBO emails kpi@ directly once we get
#     the recipient configured upstream)
#   * forwarded FedEx senders — the email arrives from the forwarder's
#     address, not FedEx's. We accept Spider/AMW domains as known
#     forwarders so today's manual + auto-forward setup works.
#
# Subject regex stays specific so we don't ingest unrelated mail from
# the same forwarder addresses (random work email forwarded by accident
# shouldn't trigger the FedEx parser).
register_parser(
    "fedex_invoice",
    sender_re=(
        r"@(?:"
        r"fedex\.com|invoicing\.fedex\.com|billonline\.fedex\.com|fedexbilling\.com"
        r"|alignmachineworks\.com|spidergrills\.com|spidergrills\.app|spidergrills\.ai"
        r")"
    ),
    subject_re=r"FedEx",
    fn=_parse_fedex_invoice,
)
