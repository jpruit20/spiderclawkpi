"""Bridge: for each Freshdesk ticket whose requester has a MAC linkage
via AppSideDeviceObservation, find TelemetrySessions for that MAC
within ±2h of the ticket's creation time and summarize them.

Powers the "this ticket was opened during a cook that overshot by 85°F"
overlay on VOC/support surfaces, and fuels the AI insight engine's
"Freshdesk spike correlates with rollout X" observations.

Ticket → MAC resolution goes through ``AppSideDeviceObservation``
because Freshdesk doesn't natively store device MAC on tickets — our
app bridge extracts ``cf_mac_adr`` from the custom_fields payload at
ticket creation.

MAC → device_id (DDB thingName hash) is resolved via the MAC JSONB
expression index on TelemetryStreamEvent (migration 0036). Since a
single physical grill can pair with multiple user accounts → multiple
device_id values, we resolve all of them.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.models import (
    AppSideDeviceObservation,
    FreshdeskCookCorrelation,
    FreshdeskTicket,
    TelemetrySession,
    TelemetryStreamEvent,
)


logger = logging.getLogger(__name__)


CORRELATION_WINDOW_HOURS = 2


def _resolve_mac_for_requester(
    db: Session,
    requester_id: Optional[str],
    ticket_id: str,
) -> Optional[str]:
    """Pick the most recently-observed MAC for this requester or ticket.

    Preference order:
      1. ``source='freshdesk', source_ref_id=ticket_id`` — direct
         match (the bridge records one obs per ticket).
      2. ``user_key=requester_id`` observed most recently.
    """
    # 1. Direct ticket hit.
    row = db.execute(
        select(AppSideDeviceObservation)
        .where(AppSideDeviceObservation.source == "freshdesk")
        .where(AppSideDeviceObservation.source_ref_id == str(ticket_id))
    ).scalars().first()
    if row and row.mac_normalized:
        return row.mac_normalized

    if requester_id:
        row = db.execute(
            select(AppSideDeviceObservation)
            .where(AppSideDeviceObservation.user_key == str(requester_id))
            .where(AppSideDeviceObservation.mac_normalized.is_not(None))
            .order_by(AppSideDeviceObservation.observed_at.desc().nullslast())
            .limit(1)
        ).scalars().first()
        if row and row.mac_normalized:
            return row.mac_normalized
    return None


def _device_ids_for_mac(db: Session, mac: str) -> list[str]:
    """Resolve a MAC to all DDB thingName hashes that have reported it.

    Uses the JSONB expression index on
    ``raw_payload->device_data->reported->>mac`` (migration 0036).
    """
    rows = db.execute(
        select(TelemetryStreamEvent.device_id)
        .where(TelemetryStreamEvent.raw_payload["device_data"]["reported"]["mac"].astext == mac)
        .distinct()
    ).all()
    return [r[0] for r in rows if r[0]]


def _summarize_session(s: TelemetrySession) -> dict[str, Any]:
    return {
        "session_id": s.session_id,
        "start": s.session_start.isoformat() if s.session_start else None,
        "end": s.session_end.isoformat() if s.session_end else None,
        "duration_seconds": s.session_duration_seconds,
        "target_temp": s.target_temp,
        "cook_intent": s.cook_intent,
        "cook_outcome": s.cook_outcome,
        "held_target": s.held_target,
        "in_control_pct": s.in_control_pct,
        "disturbance_count": s.disturbance_count,
        "max_overshoot_f": s.max_overshoot_f,
        "max_undershoot_f": s.max_undershoot_f,
        "error_count": s.error_count,
        "firmware_version": s.firmware_version,
    }


def correlate_ticket(
    db: Session,
    ticket: FreshdeskTicket,
    *,
    window_hours: int = CORRELATION_WINDOW_HOURS,
) -> Optional[FreshdeskCookCorrelation]:
    """Compute or refresh a single ticket's correlation row. Returns
    None if no MAC resolvable OR no sessions in the window."""
    if ticket.created_at_source is None:
        return None
    mac = _resolve_mac_for_requester(db, ticket.requester_id, ticket.ticket_id)
    if not mac:
        return None

    device_ids = _device_ids_for_mac(db, mac)
    if not device_ids:
        # No telemetry has ever landed for this MAC — but still record the
        # ticket→MAC bridge so future telemetry lights it up.
        row = _upsert_correlation(
            db, ticket.ticket_id, mac,
            ticket.created_at_source,
            ticket.created_at_source - timedelta(hours=window_hours),
            ticket.created_at_source + timedelta(hours=window_hours),
            sessions_matched=0,
            evidence={"mac_resolution": True, "device_ids": []},
        )
        return row

    start = ticket.created_at_source - timedelta(hours=window_hours)
    end = ticket.created_at_source + timedelta(hours=window_hours)

    sessions = db.execute(
        select(TelemetrySession)
        .where(TelemetrySession.device_id.in_(device_ids))
        .where(
            or_(
                and_(TelemetrySession.session_start >= start, TelemetrySession.session_start <= end),
                and_(TelemetrySession.session_end >= start, TelemetrySession.session_end <= end),
                and_(TelemetrySession.session_start <= start, TelemetrySession.session_end >= start),
            )
        )
        .order_by(TelemetrySession.session_start)
    ).scalars().all()

    evidence = {
        "mac_resolution": True,
        "device_ids": device_ids,
        "sessions": [_summarize_session(s) for s in sessions],
    }
    return _upsert_correlation(
        db, ticket.ticket_id, mac,
        ticket.created_at_source, start, end,
        sessions_matched=len(sessions),
        evidence=evidence,
    )


def _upsert_correlation(
    db: Session,
    ticket_id: str,
    mac: str,
    ticket_created_at: Optional[datetime],
    window_start: Optional[datetime],
    window_end: Optional[datetime],
    *,
    sessions_matched: int,
    evidence: dict[str, Any],
) -> FreshdeskCookCorrelation:
    row = db.execute(
        select(FreshdeskCookCorrelation).where(FreshdeskCookCorrelation.ticket_id == ticket_id)
    ).scalars().first()
    now = datetime.now(timezone.utc)
    if row is None:
        row = FreshdeskCookCorrelation(
            ticket_id=ticket_id,
            mac_normalized=mac,
            ticket_created_at=ticket_created_at,
            window_start=window_start,
            window_end=window_end,
            sessions_matched=sessions_matched,
            evidence_json=evidence,
            computed_at=now,
        )
        db.add(row)
    else:
        row.mac_normalized = mac
        row.ticket_created_at = ticket_created_at
        row.window_start = window_start
        row.window_end = window_end
        row.sessions_matched = sessions_matched
        row.evidence_json = evidence
        row.computed_at = now
    return row


def run_freshdesk_cook_correlation(
    db: Session,
    *,
    lookback_days: int = 14,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Nightly job: re-correlate every ticket from the last N days. Cheap
    enough to rebuild — Freshdesk ticket volume is modest."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=lookback_days)

    tickets = db.execute(
        select(FreshdeskTicket)
        .where(FreshdeskTicket.created_at_source >= cutoff)
        .order_by(FreshdeskTicket.created_at_source.desc())
    ).scalars().all()

    processed = 0
    linked = 0
    with_sessions = 0
    for t in tickets:
        try:
            row = correlate_ticket(db, t)
            processed += 1
            if row:
                linked += 1
                if row.sessions_matched > 0:
                    with_sessions += 1
        except Exception:
            logger.exception("correlate_ticket failed for %s", t.ticket_id)
            db.rollback()
    db.commit()
    return {
        "tickets_processed": processed,
        "tickets_linked_to_mac": linked,
        "tickets_with_cook_sessions": with_sessions,
        "run_at": now.isoformat(),
    }
