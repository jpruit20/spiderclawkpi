from collections import defaultdict
from datetime import datetime, timedelta, timezone
import logging
import time
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import FreshdeskAgentDaily, FreshdeskGroupsDaily, FreshdeskTicket, FreshdeskTicketEvent, FreshdeskTicketsDaily
from app.services.source_health import finish_sync_run, start_sync_run, upsert_source_config


settings = get_settings()
logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(logging.Formatter('%(levelname)s:%(name)s:%(message)s'))
    logger.addHandler(stream_handler)
TIMEOUT_SECONDS = 45
BUSINESS_TZ = ZoneInfo("America/New_York")


def _business_date(value: datetime | None):
    if value is None:
        return None
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(BUSINESS_TZ).date()


def normalize_freshdesk_base_url(raw_value: Any) -> str:
    if raw_value is None:
        raise ValueError("Freshdesk domain is not configured")

    raw = str(raw_value).strip()
    if not raw:
        raise ValueError("Freshdesk domain is empty")

    raw = raw.replace(" ", "")
    raw = raw.rstrip("/")

    if raw.startswith("http://") or raw.startswith("https://"):
        parsed = urlparse(raw)
        raw = parsed.netloc or parsed.path

    raw = raw.replace("https://", "").replace("http://", "").strip().strip("/")

    if raw.endswith(".freshdesk.com/api/v2"):
        raw = raw[: -len("/api/v2")]

    if raw.count(".freshdesk.com") > 1:
        raise ValueError(f"Freshdesk domain contains duplicate suffix: {raw}")

    if ".freshdesk.com" not in raw:
        raw = f"{raw}.freshdesk.com"

    if " " in raw:
        raise ValueError(f"Freshdesk domain contains spaces: {raw!r}")

    if raw.count(".freshdesk.com") != 1:
        raise ValueError(f"Freshdesk domain is malformed after normalization: {raw}")

    base_url = f"https://{raw}/api/v2"

    if " " in base_url:
        raise ValueError(f"Freshdesk base URL contains spaces: {base_url!r}")
    if ".freshdesk.com/.freshdesk.com" in base_url or ".freshdesk.com.freshdesk.com" in base_url:
        raise ValueError(f"Freshdesk base URL contains duplicate domain: {base_url}")

    return base_url


def _configured() -> bool:
    try:
        normalize_freshdesk_base_url(settings.freshdesk_domain)
    except ValueError:
        return False
    return bool(settings.freshdesk_api_key)


def _auth() -> tuple[str, str]:
    # Freshdesk API key auth uses the API key as the username and a dummy
    # password (commonly "X"). The prior implementation used
    # FRESHDESK_API_USER as the password, which can cause 401s when that
    # env var stores a display label/name rather than an actual password.
    return settings.freshdesk_api_key or "", "X"


def _base_url() -> str:
    base_url = normalize_freshdesk_base_url(settings.freshdesk_domain)
    logger.info("freshdesk resolved base url", extra={"resolved_base_url": base_url})
    return base_url


def _request_tickets(base_url: str, params: dict[str, Any], headers: dict[str, str]) -> requests.Response:
    request_url = f"{base_url}/tickets"
    if " " in request_url:
        raise ValueError(f"Freshdesk request URL contains spaces: {request_url!r}")
    if ".freshdesk.com/.freshdesk.com" in request_url or ".freshdesk.com.freshdesk.com" in request_url:
        raise ValueError(f"Freshdesk request URL contains duplicate domain: {request_url}")
    logger.info("freshdesk request", extra={"resolved_base_url": base_url, "request_url": request_url})
    return requests.get(
        request_url,
        auth=_auth(),
        headers=headers,
        params=params,
        timeout=TIMEOUT_SECONDS,
    )


def _clean_exception_message(exc: Exception, base_url: str | None = None) -> str:
    message = str(exc)
    if base_url:
        message = message.replace(f"host='{base_url}'", f"host='{urlparse(base_url).netloc}'")
        message = message.replace(base_url, urlparse(base_url).netloc)
    return message


def _extract_first_response_hours(ticket: dict[str, Any]) -> float:
    stats = ticket.get("stats") or {}
    for key in ["first_responded_at", "first_response_time_in_seconds", "first_response_time"]:
        value = stats.get(key)
        if isinstance(value, (int, float)):
            if "seconds" in key:
                return float(value) / 3600.0
            return float(value)
    return 0.0


def _rebuild_daily_marts(db: Session, start_date, end_date) -> None:
    if start_date is None or end_date is None or start_date > end_date:
        return

    tickets = db.execute(select(FreshdeskTicket)).scalars().all()

    grouped_daily: dict[datetime.date, dict[str, Any]] = defaultdict(lambda: {
        "tickets_created": 0,
        "tickets_resolved": 0,
        "unresolved_tickets": 0,
        "reopened_tickets": 0,
        "first_response_hours_total": 0.0,
        "first_response_count": 0,
        "resolution_hours_total": 0.0,
        "resolution_count": 0,
        "sla_breaches": 0,
        "csat_total": 0.0,
        "csat_count": 0,
    })
    grouped_agent: dict[tuple[datetime.date, str], dict[str, Any]] = defaultdict(lambda: {
        "tickets_resolved": 0,
        "first_response_hours_total": 0.0,
        "first_response_count": 0,
        "resolution_hours_total": 0.0,
        "resolution_count": 0,
        "agent_name": None,
    })
    grouped_group: dict[tuple[datetime.date, str], dict[str, Any]] = defaultdict(lambda: {
        "tickets_created": 0,
        "tickets_resolved": 0,
        "unresolved_tickets": 0,
    })

    current_day = start_date
    while current_day <= end_date:
        grouped_daily[current_day]
        current_day += timedelta(days=1)

    for ticket in tickets:
        created_business_date = _business_date(ticket.created_at_source)
        resolved_business_date = _business_date(ticket.resolved_at_source)
        updated_business_date = _business_date(ticket.updated_at_source)
        if created_business_date is None:
            continue

        status = str(ticket.status or "unknown")
        group_name = str(ticket.group_name or "unassigned")
        agent_id = str(ticket.agent_id or "unassigned")
        fr_hours = float(ticket.first_response_hours or 0.0)
        res_hours = float(ticket.resolution_hours or 0.0)
        csat = float(ticket.csat_score or 0.0)
        reopened = 1 if status.lower() in {"reopened", "4"} else 0
        raw_payload = ticket.raw_payload or {}
        sla_breach = 1 if raw_payload.get("fr_escalated") or raw_payload.get("is_escalated") else 0

        if start_date <= created_business_date <= end_date:
            grouped_daily[created_business_date]["tickets_created"] += 1
            grouped_daily[created_business_date]["reopened_tickets"] += reopened
            grouped_daily[created_business_date]["sla_breaches"] += sla_breach
            if fr_hours > 0:
                grouped_daily[created_business_date]["first_response_hours_total"] += fr_hours
                grouped_daily[created_business_date]["first_response_count"] += 1
            if csat > 0:
                grouped_daily[created_business_date]["csat_total"] += csat
                grouped_daily[created_business_date]["csat_count"] += 1
            grouped_group[(created_business_date, group_name)]["tickets_created"] += 1
            grouped_agent[(created_business_date, agent_id)]["agent_name"] = agent_id
            if fr_hours > 0:
                grouped_agent[(created_business_date, agent_id)]["first_response_hours_total"] += fr_hours
                grouped_agent[(created_business_date, agent_id)]["first_response_count"] += 1

        if resolved_business_date is not None and start_date <= resolved_business_date <= end_date:
            grouped_daily[resolved_business_date]["tickets_resolved"] += 1
            if res_hours > 0:
                grouped_daily[resolved_business_date]["resolution_hours_total"] += res_hours
                grouped_daily[resolved_business_date]["resolution_count"] += 1
            grouped_group[(resolved_business_date, group_name)]["tickets_resolved"] += 1
            grouped_agent[(resolved_business_date, agent_id)]["tickets_resolved"] += 1
            grouped_agent[(resolved_business_date, agent_id)]["agent_name"] = agent_id
            if res_hours > 0:
                grouped_agent[(resolved_business_date, agent_id)]["resolution_hours_total"] += res_hours
                grouped_agent[(resolved_business_date, agent_id)]["resolution_count"] += 1

        if resolved_business_date is None:
            backlog_start = max(created_business_date, start_date)
            backlog_end = end_date
            current_backlog_day = backlog_start
            while current_backlog_day <= backlog_end:
                grouped_daily[current_backlog_day]["unresolved_tickets"] += 1
                grouped_group[(current_backlog_day, group_name)]["unresolved_tickets"] += 1
                current_backlog_day += timedelta(days=1)
        elif updated_business_date is not None and start_date <= updated_business_date <= end_date and resolved_business_date > updated_business_date:
            current_backlog_day = max(created_business_date, start_date)
            backlog_end = min(resolved_business_date - timedelta(days=1), end_date)
            while current_backlog_day <= backlog_end:
                grouped_daily[current_backlog_day]["unresolved_tickets"] += 1
                grouped_group[(current_backlog_day, group_name)]["unresolved_tickets"] += 1
                current_backlog_day += timedelta(days=1)

    for day in [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]:
        row = db.execute(select(FreshdeskTicketsDaily).where(FreshdeskTicketsDaily.business_date == day)).scalars().first()
        if row is None:
            row = FreshdeskTicketsDaily(business_date=day)
            db.add(row)
        values = grouped_daily[day]
        row.tickets_created = values["tickets_created"]
        row.tickets_resolved = values["tickets_resolved"]
        row.unresolved_tickets = values["unresolved_tickets"]
        row.reopened_tickets = values["reopened_tickets"]
        row.first_response_hours = values["first_response_hours_total"] / values["first_response_count"] if values["first_response_count"] else 0.0
        row.resolution_hours = values["resolution_hours_total"] / values["resolution_count"] if values["resolution_count"] else 0.0
        row.sla_breach_rate = values["sla_breaches"] / values["tickets_created"] * 100.0 if values["tickets_created"] else 0.0
        row.csat = values["csat_total"] / values["csat_count"] if values["csat_count"] else 0.0

    for (business_date, agent_id), values in grouped_agent.items():
        if not (start_date <= business_date <= end_date):
            continue
        row = db.execute(select(FreshdeskAgentDaily).where(FreshdeskAgentDaily.business_date == business_date, FreshdeskAgentDaily.agent_id == agent_id)).scalars().first()
        if row is None:
            row = FreshdeskAgentDaily(business_date=business_date, agent_id=agent_id)
            db.add(row)
        row.agent_name = values["agent_name"]
        row.tickets_resolved = values["tickets_resolved"]
        row.first_response_hours = values["first_response_hours_total"] / values["first_response_count"] if values["first_response_count"] else 0.0
        row.resolution_hours = values["resolution_hours_total"] / values["resolution_count"] if values["resolution_count"] else 0.0

    for (business_date, group_name), values in grouped_group.items():
        if not (start_date <= business_date <= end_date):
            continue
        row = db.execute(select(FreshdeskGroupsDaily).where(FreshdeskGroupsDaily.business_date == business_date, FreshdeskGroupsDaily.group_name == group_name)).scalars().first()
        if row is None:
            row = FreshdeskGroupsDaily(business_date=business_date, group_name=group_name)
            db.add(row)
        row.tickets_created = values["tickets_created"]
        row.tickets_resolved = values["tickets_resolved"]
        row.unresolved_tickets = values["unresolved_tickets"]


def sync_freshdesk(db: Session, days: int = 30) -> dict[str, Any]:
    started = time.monotonic()
    resolved_base_url = None
    try:
        resolved_base_url = normalize_freshdesk_base_url(settings.freshdesk_domain)
    except ValueError:
        resolved_base_url = None

    configured = bool(resolved_base_url and settings.freshdesk_api_key)
    upsert_source_config(
        db,
        "freshdesk",
        configured=configured,
        sync_mode="poll",
        config_json={"resolved_base_url": resolved_base_url},
    )
    db.commit()

    if not configured:
        return {"ok": False, "message": "Freshdesk not configured", "records_processed": 0}

    run = start_sync_run(db, "freshdesk", "poll_recent", {"days": days, "resolved_base_url": resolved_base_url})
    db.commit()

    stats = {
        "records_fetched": 0,
        "records_inserted": 0,
        "records_updated": 0,
        "duplicates_skipped": 0,
    }

    try:
        params = {
            "updated_since": (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "per_page": 100,
            "page": 1,
            "include": "stats",
        }
        headers = {"Accept": "application/json"}
        all_tickets: list[dict[str, Any]] = []
        seen_ticket_ids: set[str] = set()
        base_url = _base_url()

        while True:
            response = _request_tickets(base_url, params, headers)
            response.raise_for_status()
            batch = response.json()
            stats["records_fetched"] += len(batch)
            if not batch:
                break
            for ticket in batch:
                ticket_id = str(ticket.get("id"))
                if ticket_id in seen_ticket_ids:
                    stats["duplicates_skipped"] += 1
                    continue
                seen_ticket_ids.add(ticket_id)
                all_tickets.append(ticket)
            params["page"] += 1
            if len(batch) < 100:
                break

        affected_dates: set[datetime.date] = set()

        for ticket in all_tickets:
            ticket_id = str(ticket.get("id"))
            created_at = datetime.fromisoformat(ticket["created_at"].replace("Z", "+00:00"))
            updated_at = datetime.fromisoformat(ticket["updated_at"].replace("Z", "+00:00"))
            resolved_at = None
            if ticket.get("resolved_at"):
                resolved_at = datetime.fromisoformat(ticket["resolved_at"].replace("Z", "+00:00"))

            created_business_date = _business_date(created_at)
            resolved_business_date = _business_date(resolved_at) if resolved_at else None
            snapshot_business_date = _business_date(updated_at)
            if created_business_date:
                affected_dates.add(created_business_date)
            if resolved_business_date:
                affected_dates.add(resolved_business_date)
            if snapshot_business_date:
                affected_dates.add(snapshot_business_date)
            status = str(ticket.get("status_name") or ticket.get("status") or "unknown")
            priority = str(ticket.get("priority") or "unknown")
            channel = str(ticket.get("source") or "unknown")
            group_name = str(ticket.get("group_id") or "unassigned")
            agent_id = str(ticket.get("responder_id") or "unassigned")
            fr_hours = _extract_first_response_hours(ticket)
            res_hours = ((resolved_at - created_at).total_seconds() / 3600.0) if resolved_at else 0.0
            csat = float(ticket.get("satisfaction_rating", {}).get("score") or 0.0)
            record = db.execute(select(FreshdeskTicket).where(FreshdeskTicket.ticket_id == ticket_id)).scalars().first()
            if record is None:
                record = FreshdeskTicket(ticket_id=ticket_id)
                db.add(record)
                stats["records_inserted"] += 1
            else:
                stats["records_updated"] += 1
            record.subject = ticket.get("subject")
            record.status = status
            record.priority = priority
            record.channel = channel
            record.group_name = group_name
            record.requester_id = str(ticket.get("requester_id") or "") or None
            record.agent_id = agent_id
            record.created_at_source = created_at
            record.updated_at_source = updated_at
            record.resolved_at_source = resolved_at
            record.first_response_hours = fr_hours
            record.resolution_hours = res_hours
            record.csat_score = csat if csat > 0 else None
            record.tags_json = ticket.get("tags") or []
            record.category = (ticket.get("tags") or [None])[0]
            record.raw_payload = ticket

            existing_event = db.execute(
                select(FreshdeskTicketEvent)
                .where(
                    FreshdeskTicketEvent.ticket_id == ticket_id,
                    FreshdeskTicketEvent.event_type == "poll.ticket_snapshot",
                    FreshdeskTicketEvent.event_timestamp == updated_at,
                )
                .limit(1)
            ).scalars().first()
            if existing_event is None:
                db.add(
                    FreshdeskTicketEvent(
                        ticket_id=ticket_id,
                        event_type="poll.ticket_snapshot",
                        event_timestamp=updated_at,
                        raw_payload=ticket,
                        normalized_payload={
                            "status": status,
                            "priority": priority,
                            "channel": channel,
                            "group_name": group_name,
                        },
                    )
                )
            else:
                stats["duplicates_skipped"] += 1

        if affected_dates:
            rebuild_start = min(affected_dates)
            rebuild_end = max(max(affected_dates), _business_date(datetime.now(timezone.utc)))
            _rebuild_daily_marts(db, rebuild_start, rebuild_end)

        duration_ms = int((time.monotonic() - started) * 1000)
        run.metadata_json = {**run.metadata_json, **stats, "duration_ms": duration_ms, "resolved_base_url": base_url}
        finish_sync_run(db, run, status="success", records_processed=len(all_tickets))
        db.commit()
        logger.info("freshdesk sync complete", extra={"stats": stats, "duration_ms": duration_ms, "resolved_base_url": base_url})
        return {"ok": True, "records_processed": len(all_tickets), **stats, "duration_ms": duration_ms, "resolved_base_url": base_url}
    except Exception as exc:
        db.rollback()
        run = db.merge(run)
        duration_ms = int((time.monotonic() - started) * 1000)
        clean_message = _clean_exception_message(exc, resolved_base_url)
        run.metadata_json = {**(run.metadata_json or {}), **stats, "duration_ms": duration_ms, "resolved_base_url": resolved_base_url}
        finish_sync_run(db, run, status="failed", error_message=clean_message)
        db.commit()
        logger.exception("freshdesk sync failed")
        return {"ok": False, "message": clean_message, "records_processed": 0, **stats, "duration_ms": duration_ms, "resolved_base_url": resolved_base_url}
