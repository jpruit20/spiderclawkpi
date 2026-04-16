"""Materialize Spider Grills *app-side* fleet observations.

This module populates three tables:

  * ``app_side_user_observations``    — one row per (source, source_ref_id)
  * ``app_side_device_observations``  — one row per (source, source_ref_id)
  * ``app_side_daily``                — per-(business_date, source) rollup

Every row is explicitly tagged with a ``source`` discriminator so the
Freshdesk-derived stream and the future direct ``spidergrills.app`` backend
pull can coexist, be reported separately, and be merged (deduplicated by MAC
/ user_key) without double-counting.

Phase 1 (this module): only the ``freshdesk`` source is populated, mined from
the existing ``freshdesk_tickets.raw_payload`` JSON that the Freshdesk
connector already stores. No new network calls, no new credentials required.

Phase 2 (follow-up): add ``sync_app_backend(db)`` that writes rows with
``source='app_backend'`` from a direct database read of spidergrills.app.
The ``rebuild_app_side_daily`` rollup function here is source-agnostic and
will pick up both automatically.
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    AppSideDaily,
    AppSideDeviceObservation,
    AppSideUserObservation,
    FreshdeskTicket,
)


logger = logging.getLogger(__name__)
BUSINESS_TZ = ZoneInfo("America/New_York")

SOURCE_FRESHDESK = "freshdesk"
SOURCE_APP_BACKEND = "app_backend"

# Freshdesk custom_field keys the app posts on each [AUTOMATED] diagnostic
# ticket. Keys are field-ID-suffixed in Freshdesk so we match by stable prefix.
_FIELD_PATTERNS = {
    "controller_model": re.compile(r"^cf_controller_model"),
    "phone_brand": re.compile(r"^cf_phone_brand"),
    "phone_model": re.compile(r"^cf_phone_model$"),
    "phone_os": re.compile(r"^cf_phone_operative_system$"),
    "phone_os_version": re.compile(r"^cf_phone_operating_system"),
    "mac_address": re.compile(r"^cf_mac_adr"),  # ticket payload typo: "cf_mac_adreess"
    "firmware_version": re.compile(r"^cf_firmware_version"),
    "app_version": re.compile(r"^cf_app_version"),
}


def _extract_app_fields(custom_fields: dict[str, Any]) -> dict[str, Any]:
    """Pull app-side fields from a Freshdesk custom_fields blob by prefix match."""
    out: dict[str, Any] = {k: None for k in _FIELD_PATTERNS}
    if not isinstance(custom_fields, dict):
        return out
    for key, value in custom_fields.items():
        if value in (None, "", []):
            continue
        for canonical, pattern in _FIELD_PATTERNS.items():
            if out[canonical] is None and pattern.match(key):
                out[canonical] = str(value).strip() or None
                break
    return out


def _normalize_mac(raw: str | None) -> str | None:
    if not raw:
        return None
    hex_only = re.sub(r"[^0-9A-Fa-f]", "", str(raw))
    if len(hex_only) != 12:
        return None
    normalized = hex_only.lower()
    # The app logs show redacted MACs like "02:00:00:00:00:00" on Android 11+ —
    # drop them to avoid collapsing every Android user into one "device".
    if normalized == "020000000000":
        return None
    return normalized


def _user_key(email: str | None) -> str | None:
    if not email:
        return None
    cleaned = email.strip().lower()
    if "@" not in cleaned:
        return None
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()


def _email_domain(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    return email.split("@", 1)[1].strip().lower() or None


def _business_date(value: datetime | None) -> date | None:
    if value is None:
        return None
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(BUSINESS_TZ).date()


def _requester_email_from_ticket(ticket: FreshdeskTicket) -> str | None:
    payload = ticket.raw_payload or {}
    email = payload.get("email") or payload.get("requester_email")
    if not email:
        requester = payload.get("requester") or {}
        if isinstance(requester, dict):
            email = requester.get("email") or requester.get("login_email")
    if not email:
        # For auto-generated diagnostic tickets, the app writes the user's
        # email into the description's "ticket" blob — fall back to the
        # requester_id if we can't find anything better.
        email = payload.get("description_text_email")
    return str(email).strip() if email else None


def ingest_freshdesk_observations(db: Session) -> dict[str, int]:
    """Read every FreshdeskTicket and upsert user/device observations.

    Idempotent — keyed on (source, source_ref_id). Returns counts.
    """
    stats = {
        "tickets_seen": 0,
        "user_rows_inserted": 0,
        "user_rows_updated": 0,
        "device_rows_inserted": 0,
        "device_rows_updated": 0,
        "tickets_skipped_no_date": 0,
        "tickets_skipped_no_user": 0,
    }

    tickets = db.execute(select(FreshdeskTicket)).scalars().all()
    stats["tickets_seen"] = len(tickets)

    for ticket in tickets:
        bdate = _business_date(ticket.created_at_source)
        if bdate is None:
            stats["tickets_skipped_no_date"] += 1
            continue

        payload = ticket.raw_payload or {}
        custom = payload.get("custom_fields") or {}
        fields = _extract_app_fields(custom)

        email = _requester_email_from_ticket(ticket)
        user_key = _user_key(email)

        # --- user observation ----------------------------------------------
        if user_key:
            source_ref = f"freshdesk:{ticket.ticket_id}"
            user_row = db.execute(
                select(AppSideUserObservation).where(
                    AppSideUserObservation.source == SOURCE_FRESHDESK,
                    AppSideUserObservation.source_ref_id == source_ref,
                )
            ).scalars().first()
            if user_row is None:
                user_row = AppSideUserObservation(
                    source=SOURCE_FRESHDESK,
                    source_ref_id=source_ref,
                    business_date=bdate,
                    user_key=user_key,
                    email=email,
                    email_domain=_email_domain(email),
                    observed_at=ticket.created_at_source,
                    raw_payload={
                        "ticket_id": ticket.ticket_id,
                        "subject": ticket.subject,
                        "channel": ticket.channel,
                        "status": ticket.status,
                        "tags": ticket.tags_json,
                    },
                )
                db.add(user_row)
                stats["user_rows_inserted"] += 1
            else:
                user_row.business_date = bdate
                user_row.user_key = user_key
                user_row.email = email
                user_row.email_domain = _email_domain(email)
                user_row.observed_at = ticket.created_at_source
                stats["user_rows_updated"] += 1
        else:
            stats["tickets_skipped_no_user"] += 1

        # --- device observation -------------------------------------------
        mac_norm = _normalize_mac(fields["mac_address"])
        controller = fields["controller_model"]
        firmware = fields["firmware_version"]
        app_version = fields["app_version"]
        phone_os = fields["phone_os"]
        phone_os_version = fields["phone_os_version"]
        phone_brand = fields["phone_brand"]
        phone_model = fields["phone_model"]

        # Only write a device row if the ticket carries *any* app-side signal
        # (MAC, firmware, app version, controller, or phone context).
        any_signal = any([
            mac_norm, controller, firmware, app_version,
            phone_os, phone_brand, phone_model,
        ])
        if not any_signal:
            continue

        source_ref = f"freshdesk:{ticket.ticket_id}"
        device_row = db.execute(
            select(AppSideDeviceObservation).where(
                AppSideDeviceObservation.source == SOURCE_FRESHDESK,
                AppSideDeviceObservation.source_ref_id == source_ref,
            )
        ).scalars().first()
        if device_row is None:
            device_row = AppSideDeviceObservation(
                source=SOURCE_FRESHDESK,
                source_ref_id=source_ref,
                business_date=bdate,
                user_key=user_key,
                mac_raw=fields["mac_address"],
                mac_normalized=mac_norm,
                controller_model=controller,
                firmware_version=firmware,
                app_version=app_version,
                phone_os=phone_os,
                phone_os_version=phone_os_version,
                phone_brand=phone_brand,
                phone_model=phone_model,
                observed_at=ticket.created_at_source,
                raw_payload={"custom_fields": custom, "ticket_id": ticket.ticket_id},
            )
            db.add(device_row)
            stats["device_rows_inserted"] += 1
        else:
            device_row.business_date = bdate
            device_row.user_key = user_key
            device_row.mac_raw = fields["mac_address"]
            device_row.mac_normalized = mac_norm
            device_row.controller_model = controller
            device_row.firmware_version = firmware
            device_row.app_version = app_version
            device_row.phone_os = phone_os
            device_row.phone_os_version = phone_os_version
            device_row.phone_brand = phone_brand
            device_row.phone_model = phone_model
            device_row.observed_at = ticket.created_at_source
            stats["device_rows_updated"] += 1

    db.flush()
    return stats


def _build_dist(values: Iterable[str | None], top_n: int | None = None) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for v in values:
        if v is None:
            continue
        counter[str(v)] += 1
    if top_n is None:
        return dict(counter)
    return dict(counter.most_common(top_n))


def rebuild_app_side_daily(db: Session) -> dict[str, int]:
    """Rebuild the ``app_side_daily`` rollup from observation rows.

    Source-agnostic: aggregates independently per (business_date, source), so
    adding ``app_backend`` rows later requires no change here. Always a full
    rebuild — cheap at our volumes and keeps the rollup exactly consistent.
    """
    users = db.execute(select(AppSideUserObservation)).scalars().all()
    devices = db.execute(select(AppSideDeviceObservation)).scalars().all()

    # (business_date, source) -> lists
    user_keys_by: dict[tuple[date, str], set[str]] = defaultdict(set)
    user_observations_by: dict[tuple[date, str], int] = defaultdict(int)
    for u in users:
        key = (u.business_date, u.source)
        user_keys_by[key].add(u.user_key)
        user_observations_by[key] += 1

    device_keys_by: dict[tuple[date, str], set[str]] = defaultdict(set)
    device_observations_by: dict[tuple[date, str], int] = defaultdict(int)
    app_version_by: dict[tuple[date, str], list[str | None]] = defaultdict(list)
    firmware_by: dict[tuple[date, str], list[str | None]] = defaultdict(list)
    controller_by: dict[tuple[date, str], list[str | None]] = defaultdict(list)
    phone_os_by: dict[tuple[date, str], list[str | None]] = defaultdict(list)
    phone_brand_by: dict[tuple[date, str], list[str | None]] = defaultdict(list)
    phone_model_by: dict[tuple[date, str], list[str | None]] = defaultdict(list)

    for d in devices:
        key = (d.business_date, d.source)
        device_observations_by[key] += 1
        if d.mac_normalized:
            device_keys_by[key].add(d.mac_normalized)
        app_version_by[key].append(d.app_version)
        firmware_by[key].append(d.firmware_version)
        controller_by[key].append(d.controller_model)
        phone_os_by[key].append(d.phone_os)
        phone_brand_by[key].append(d.phone_brand)
        phone_model_by[key].append(d.phone_model)

    # Full rebuild — wipe and re-insert.
    db.execute(delete(AppSideDaily))
    db.flush()

    all_keys = set(user_keys_by.keys()) | set(device_keys_by.keys()) | set(device_observations_by.keys()) | set(user_observations_by.keys())
    rows_written = 0
    for key in sorted(all_keys):
        bdate, source = key
        row = AppSideDaily(
            business_date=bdate,
            source=source,
            observations=user_observations_by.get(key, 0) + device_observations_by.get(key, 0),
            unique_users=len(user_keys_by.get(key, set())),
            unique_devices=len(device_keys_by.get(key, set())),
            app_version_dist=_build_dist(app_version_by.get(key, []), top_n=20),
            firmware_version_dist=_build_dist(firmware_by.get(key, []), top_n=20),
            controller_model_dist=_build_dist(controller_by.get(key, []), top_n=20),
            phone_os_dist=_build_dist(phone_os_by.get(key, []), top_n=10),
            phone_brand_dist=_build_dist(phone_brand_by.get(key, []), top_n=10),
            phone_model_dist=_build_dist(phone_model_by.get(key, []), top_n=20),
        )
        db.add(row)
        rows_written += 1

    db.flush()
    return {"rows_written": rows_written}


def materialize_app_side(db: Session) -> dict[str, Any]:
    """Top-level entry point: ingest Freshdesk observations + rebuild rollup."""
    started = datetime.now(timezone.utc)
    ingest_stats = ingest_freshdesk_observations(db)
    rollup_stats = rebuild_app_side_daily(db)
    db.commit()
    duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    result = {
        "ok": True,
        "duration_ms": duration_ms,
        **ingest_stats,
        **rollup_stats,
    }
    logger.info("app_side materialize complete: %s", result)
    return result
