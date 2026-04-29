"""CX × Shipping correlation.

Detects WISMO ("where is my order?") tickets from Freshdesk subject +
description text, attempts to match each to a ShipStation shipment via
order number, and computes correlation metrics:

- WISMO volume + ratio (% of all CX tickets)
- Median time from order ship → WISMO ticket (the longer this is, the
  more "we shipped, customer didn't see tracking" friction)
- WISMO tickets where the order HASN'T shipped yet (real fulfillment
  delay signal)
- Carrier breakdown of WISMO sources (does FedEx generate more WISMO
  than UPS? Tells us where to invest in proactive tracking comms)
- WISMO ticket → resolution time correlation

The matcher is conservative — pulls order numbers from ticket subject
or first 200 chars of description (Spider order numbers are 4-5
digits per Shopify), and only matches when the same number appears
in our ShipStation shipments table.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


WISMO_KEYWORDS_RE = re.compile(
    r"\b("
    r"where[\s']*s?\s+(my|the)?\s*(order|package|shipment|delivery)|"
    r"tracking\s+(number|info|update|status)|"
    r"shipping\s+(status|update)|"
    r"order\s+status|"
    r"hasn[\s']*t\s+(arrived|shipped|received)|"
    r"never\s+(arrived|received)|"
    r"package\s+(stuck|lost|missing|delayed)|"
    r"haven[\s']*t\s+received|"
    r"when\s+will.*(ship|arrive|deliver)|"
    r"any\s+update.*on\s+(my|the)?\s*order|"
    r"delayed\s+(order|shipment|delivery)|"
    r"shipment\s+delay"
    r")\b",
    re.IGNORECASE,
)

# Spider order numbers in Shopify are typically 4-6 digits (e.g.
# "10970", "10842"). Pull from subject + first part of description.
ORDER_NUMBER_RE = re.compile(r"#?(\d{4,6})\b")


def is_wismo_ticket(subject: Optional[str], description: Optional[str]) -> bool:
    text_blob = f"{subject or ''}  {(description or '')[:500]}"
    return bool(WISMO_KEYWORDS_RE.search(text_blob))


def extract_order_number(subject: Optional[str], description: Optional[str]) -> Optional[str]:
    """Best-effort extraction. Looks in subject first (most reliable),
    then leading description text."""
    for src in (subject, (description or "")[:300]):
        if not src:
            continue
        m = ORDER_NUMBER_RE.search(src)
        if m:
            return m.group(1)
    return None


def cx_shipping_summary(db: Session, *, days: int = 30) -> dict[str, Any]:
    """Per-window CX-vs-shipping rollup. Surfaced on Operations + CX
    pages."""
    end_d = date.today()
    start_d = end_d - timedelta(days=days)

    # Pull recent tickets in window (we re-classify here since legacy
    # Freshdesk data has no WISMO tag).
    tickets = db.execute(text("""
        SELECT
            t.ticket_id,
            t.subject,
            t.description_text,
            t.created_at_source,
            t.resolved_at_source,
            t.first_response_hours,
            t.resolution_hours
        FROM freshdesk_tickets t
        WHERE t.created_at_source >= :start_ts
          AND t.created_at_source < :end_ts
    """), {
        "start_ts": datetime.combine(start_d, datetime.min.time(), tzinfo=timezone.utc),
        "end_ts": datetime.combine(end_d, datetime.min.time(), tzinfo=timezone.utc),
    }).all()

    total_tickets = len(tickets)
    wismo_rows = []
    matched_rows = []
    unshipped_at_wismo = 0
    median_lag_hours: list[float] = []

    for tk in tickets:
        if not is_wismo_ticket(tk.subject, tk.description_text):
            continue
        order_no = extract_order_number(tk.subject, tk.description_text)
        wismo_rows.append({
            "ticket_id": tk.ticket_id,
            "subject": (tk.subject or "")[:200],
            "created_at": tk.created_at_source.isoformat() if tk.created_at_source else None,
            "resolved_at": tk.resolved_at_source.isoformat() if tk.resolved_at_source else None,
            "first_response_hours": tk.first_response_hours,
            "resolution_hours": tk.resolution_hours,
            "extracted_order_number": order_no,
        })

        if not order_no:
            continue
        # Cost truth source: FedEx invoice when available, ShipStation
        # estimate as fallback (Joseph 2026-04-29 — see shipping_intelligence
        # for the full rationale).
        ship = db.execute(text("""
            SELECT ss.ship_date, ss.create_date, ss.carrier_code, ss.tracking_number,
                   COALESCE(fic.charge_amount_usd, ss.shipment_cost) AS shipment_cost
            FROM shipstation_shipments ss
            LEFT JOIN fedex_invoice_charges fic
              ON fic.tracking_number = ss.tracking_number
              AND fic.charge_category = 'NET'
              AND fic.is_spider = true
            WHERE ss.ss_order_number = :on
              AND ss.ss_store_id = ANY(:allowlist)
              AND ss.voided = FALSE
            ORDER BY ss.create_date DESC
            LIMIT 1
        """), {
            "on": order_no,
            "allowlist": list(__import__("app.core.config", fromlist=["get_settings"]).get_settings().shipstation_spider_store_ids or []),
        }).first()
        if not ship:
            unshipped_at_wismo += 1
            wismo_rows[-1].update({"matched_shipment": None, "shipped": False})
            continue
        wismo_rows[-1].update({
            "matched_shipment": {
                "ship_date": ship.ship_date.isoformat() if ship.ship_date else None,
                "carrier": ship.carrier_code,
                "tracking_number": ship.tracking_number,
                "shipment_cost": float(ship.shipment_cost or 0),
            },
            "shipped": ship.ship_date is not None,
        })
        if ship.ship_date and tk.created_at_source:
            ship_dt = datetime.combine(ship.ship_date, datetime.min.time(), tzinfo=timezone.utc)
            ticket_dt = tk.created_at_source if tk.created_at_source.tzinfo else tk.created_at_source.replace(tzinfo=timezone.utc)
            lag_hours = (ticket_dt - ship_dt).total_seconds() / 3600
            median_lag_hours.append(lag_hours)
        matched_rows.append(wismo_rows[-1])

    median_lag_hours.sort()
    median_lag = median_lag_hours[len(median_lag_hours) // 2] if median_lag_hours else None

    # Carrier breakdown of matched WISMO
    by_carrier: dict[str, int] = {}
    for r in matched_rows:
        ms = r.get("matched_shipment") or {}
        c = ms.get("carrier") or "unknown"
        by_carrier[c] = by_carrier.get(c, 0) + 1

    # Tickets where order shipped > 7 days before ticket → late-tracking-update
    # signal (we shipped but the customer never saw the email/notification)
    late_tracking_signal = sum(1 for h in median_lag_hours if h > 7 * 24)

    return {
        "window": {"start": start_d.isoformat(), "end": end_d.isoformat(), "days": days},
        "totals": {
            "tickets_in_window": total_tickets,
            "wismo_tickets": len(wismo_rows),
            "wismo_ratio_pct": round(len(wismo_rows) / total_tickets * 100, 1) if total_tickets else 0,
            "wismo_matched_to_shipment": len(matched_rows),
            "wismo_unshipped_at_ticket_time": unshipped_at_wismo,
            "median_ship_to_wismo_hours": round(median_lag, 1) if median_lag is not None else None,
            "late_tracking_signal_count": late_tracking_signal,
        },
        "by_carrier": [
            {"carrier": c, "wismo_tickets": n}
            for c, n in sorted(by_carrier.items(), key=lambda kv: -kv[1])
        ],
        "wismo_tickets": wismo_rows[:80],  # cap for the drill-down list
    }
