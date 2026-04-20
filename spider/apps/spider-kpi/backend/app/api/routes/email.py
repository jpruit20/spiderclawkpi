"""Email archive pulse endpoints.

Surfaces aggregate signals from the ``email_messages`` archive (40k+
rows, fully classified by archetype). Email is an input source — per
the entities.py comment, individual emails are never surfaced — but
archetype volume, sender-domain mix, and customer-escalation counts
are legitimate health signals for a division card.

Created 2026-04-19 overnight when wiring the archive into surfaces
the user flagged as "waiting on email data."
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_dashboard_session
from app.models import EmailMessage


BUSINESS_TZ = ZoneInfo("America/New_York")

router = APIRouter(
    prefix="/api/email",
    tags=["email"],
    dependencies=[Depends(require_dashboard_session)],
)


# Archetype → human label. Ordered by what matters most for a quick
# glance in a division card; customer-facing archetypes first.
ARCHETYPE_LABELS: dict[str, str] = {
    "customer_escalation": "Customer escalation",
    "warranty_issue": "Warranty",
    "shipment_logistics": "Shipment / logistics",
    "payment_notification": "Payment",
    "vendor_contract": "Vendor / contract",
    "supplier_discussion": "Supplier",
    "logistics_operations": "Ops logistics",
    "engineering_update": "Engineering",
    "legal_approval": "Legal",
    "partnership_inquiry": "Partnership",
    "wholesale_inquiry": "Wholesale",
    "creator_influencer": "Creator / influencer",
    "credential_sensitive": "Credential / sensitive",
    "meeting_invite": "Meeting",
    "internal_fyi": "Internal FYI",
}


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _resolve_window(
    start: Optional[str], end: Optional[str], default_days: int
) -> tuple[date, date]:
    end_d = _parse_date(end) or datetime.now(BUSINESS_TZ).date()
    start_d = _parse_date(start) or (end_d - timedelta(days=default_days - 1))
    if start_d > end_d:
        start_d, end_d = end_d, start_d
    return start_d, end_d


def _archetype_counts(
    db: Session, start_d: date, end_d: date
) -> dict[str, int]:
    start_utc = datetime.combine(start_d, datetime.min.time(), tzinfo=BUSINESS_TZ).astimezone(timezone.utc)
    end_utc = datetime.combine(end_d + timedelta(days=1), datetime.min.time(), tzinfo=BUSINESS_TZ).astimezone(timezone.utc)
    rows = db.execute(
        select(EmailMessage.archetype, func.count(EmailMessage.id))
        .where(EmailMessage.sent_at >= start_utc, EmailMessage.sent_at < end_utc)
        .group_by(EmailMessage.archetype)
    ).all()
    return {(a or "unclassified"): int(c) for a, c in rows}


def _top_domains(
    db: Session, start_d: date, end_d: date, archetype: Optional[str], limit: int
) -> list[dict[str, Any]]:
    start_utc = datetime.combine(start_d, datetime.min.time(), tzinfo=BUSINESS_TZ).astimezone(timezone.utc)
    end_utc = datetime.combine(end_d + timedelta(days=1), datetime.min.time(), tzinfo=BUSINESS_TZ).astimezone(timezone.utc)
    stmt = (
        select(EmailMessage.from_domain, func.count(EmailMessage.id).label("n"))
        .where(
            EmailMessage.sent_at >= start_utc,
            EmailMessage.sent_at < end_utc,
            EmailMessage.from_domain.isnot(None),
        )
        .group_by(EmailMessage.from_domain)
        .order_by(func.count(EmailMessage.id).desc())
        .limit(limit)
    )
    if archetype:
        stmt = stmt.where(EmailMessage.archetype == archetype)
    rows = db.execute(stmt).all()
    return [{"domain": d, "count": int(n)} for d, n in rows]


@router.get("/pulse")
def email_pulse(
    start: Optional[str] = Query(None, description="YYYY-MM-DD start (inclusive)"),
    end: Optional[str] = Query(None, description="YYYY-MM-DD end (inclusive)"),
    days: int = Query(14, ge=1, le=365),
    compare_prior: bool = Query(True),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Archetype-grouped email volume for a window, with prior-period
    deltas. Two rollups the UI actually needs:

    - ``archetypes`` — every archetype seen in the window, sorted by
      current count desc, with prior count + delta_pct.
    - ``top_customer_domains`` — top sending domains that registered
      as ``customer_escalation`` during the window (single biggest
      actionable signal in the archive).
    """
    start_d, end_d = _resolve_window(start, end, days)
    window_days = (end_d - start_d).days + 1
    prior_end = start_d - timedelta(days=1)
    prior_start = prior_end - timedelta(days=window_days - 1)

    cur_counts = _archetype_counts(db, start_d, end_d)
    prior_counts = _archetype_counts(db, prior_start, prior_end) if compare_prior else {}

    all_keys = set(cur_counts) | set(prior_counts)
    archetypes: list[dict[str, Any]] = []
    for key in all_keys:
        cur = cur_counts.get(key, 0)
        prior = prior_counts.get(key, 0)
        delta_pct = ((cur - prior) / prior * 100.0) if prior else None
        archetypes.append({
            "archetype": key,
            "label": ARCHETYPE_LABELS.get(key, key.replace("_", " ").title()),
            "count": cur,
            "prior_count": prior,
            "delta_pct": round(delta_pct, 1) if delta_pct is not None else None,
        })
    archetypes.sort(key=lambda r: r["count"], reverse=True)

    total_cur = sum(cur_counts.values())
    total_prior = sum(prior_counts.values()) if prior_counts else 0
    total_delta_pct = ((total_cur - total_prior) / total_prior * 100.0) if total_prior else None

    # Escalation-specific extras — the card's primary "what to pay
    # attention to" bucket. Top domains let us spot a single customer
    # spiral (same gmail address writing 30x in a week) separate from a
    # real spike in overall escalations.
    escalation_domains = _top_domains(db, start_d, end_d, "customer_escalation", limit=8)
    prior_esc = prior_counts.get("customer_escalation", 0)
    cur_esc = cur_counts.get("customer_escalation", 0)
    escalation_delta_pct = ((cur_esc - prior_esc) / prior_esc * 100.0) if prior_esc else None

    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "start": start_d.isoformat(),
            "end": end_d.isoformat(),
            "days": window_days,
        },
        "prior_window": {
            "start": prior_start.isoformat(),
            "end": prior_end.isoformat(),
            "days": window_days,
        } if compare_prior else None,
        "totals": {
            "count": total_cur,
            "prior_count": total_prior,
            "delta_pct": round(total_delta_pct, 1) if total_delta_pct is not None else None,
        },
        "escalations": {
            "count": cur_esc,
            "prior_count": prior_esc,
            "delta_pct": round(escalation_delta_pct, 1) if escalation_delta_pct is not None else None,
            "top_domains": escalation_domains,
        },
        "archetypes": archetypes,
    }
