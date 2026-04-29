"""Metric catalog + live value resolvers for Weekly Priority Gauges.

Opus 4.7 picks 8 gauges per week from this catalog. Each entry carries
the metadata Opus needs to reason ("direction", "category", "unit") and
a resolver that pulls the current value + 7-day sparkline from the live
database at read time. Resolvers should be cheap — they run inside the
30-second client poll cycle on the Command Center.

Direction semantics:
  * ``higher_better``  — green when above healthy_band_high
  * ``lower_better``   — green when below healthy_band_low
  * ``target``         — green when inside [healthy_band_low, healthy_band_high]
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    DeciDecision,
    FirmwareDeviceRecent,
    FreshdeskTicket,
    FreshdeskTicketsDaily,
    KPIDaily,
    Recommendation,
    ShopifyAnalyticsDaily,
    ShopifyOrderDaily,
    TelemetryDaily,
    TelemetrySession,
    TelemetryStreamEvent,
    TWSummaryDaily,
)


@dataclass
class MetricMeta:
    key: str
    label: str
    unit: str                                # "$", "%", "count", "hours", "ratio"
    category: str                            # commerce, marketing, cx, fleet, engineering, ops
    direction: str                           # higher_better | lower_better | target
    description: str                         # one-liner Opus sees when picking
    default_band: tuple[Optional[float], Optional[float]]  # (low, high) healthy band
    default_target: Optional[float] = None
    drill_href: Optional[str] = None
    resolver: Optional[Callable[[Session], dict[str, Any]]] = field(default=None, repr=False)


# ── helpers ─────────────────────────────────────────────────────────────

def _trailing_kpi_rows(db: Session, days: int = 7) -> list[KPIDaily]:
    cutoff = date.today() - timedelta(days=days + 1)
    return db.execute(
        select(KPIDaily).where(KPIDaily.business_date >= cutoff).order_by(KPIDaily.business_date)
    ).scalars().all()


def _prior_kpi_rows(db: Session, days: int = 7) -> list[KPIDaily]:
    start = date.today() - timedelta(days=2 * days + 1)
    end = date.today() - timedelta(days=days + 1)
    return db.execute(
        select(KPIDaily).where(
            KPIDaily.business_date >= start,
            KPIDaily.business_date < end,
        ).order_by(KPIDaily.business_date)
    ).scalars().all()


def _sum_attr(rows: list, attr: str) -> float:
    return float(sum((getattr(r, attr) or 0) for r in rows))


def _avg_attr(rows: list, attr: str) -> Optional[float]:
    vals = [float(getattr(r, attr)) for r in rows if getattr(r, attr) is not None]
    return sum(vals) / len(vals) if vals else None


def _daily_values(rows: list, attr: str) -> list[float]:
    return [float(getattr(r, attr) or 0) for r in rows]


def _pct_change(current: Optional[float], prior: Optional[float]) -> Optional[float]:
    if current is None or prior is None or prior == 0:
        return None
    return ((current - prior) / prior) * 100.0


# ── resolvers ───────────────────────────────────────────────────────────

def _resolve_revenue_7d(db: Session) -> dict[str, Any]:
    rows = _trailing_kpi_rows(db)
    prior = _prior_kpi_rows(db)
    value = _sum_attr(rows, "revenue")
    prior_value = _sum_attr(prior, "revenue") if prior else None
    return {
        "value": value,
        "display_value": f"${value/1000:.1f}k" if value < 1_000_000 else f"${value/1_000_000:.2f}M",
        "sparkline": _daily_values(rows, "revenue"),
        "prior_week": prior_value,
        "change_pct": _pct_change(value, prior_value),
    }


def _resolve_aov_7d(db: Session) -> dict[str, Any]:
    rows = _trailing_kpi_rows(db)
    prior = _prior_kpi_rows(db)
    rev = _sum_attr(rows, "revenue")
    orders = _sum_attr(rows, "orders")
    aov = rev / orders if orders else 0.0
    prior_rev = _sum_attr(prior, "revenue")
    prior_orders = _sum_attr(prior, "orders")
    prior_aov = prior_rev / prior_orders if prior_orders else None
    spark = [(float(r.revenue or 0) / (r.orders or 1)) if r.orders else 0.0 for r in rows]
    return {
        "value": aov,
        "display_value": f"${aov:.2f}",
        "sparkline": spark,
        "prior_week": prior_aov,
        "change_pct": _pct_change(aov, prior_aov),
    }


def _resolve_orders_7d(db: Session) -> dict[str, Any]:
    rows = _trailing_kpi_rows(db)
    prior = _prior_kpi_rows(db)
    value = _sum_attr(rows, "orders")
    prior_value = _sum_attr(prior, "orders")
    return {
        "value": value,
        "display_value": f"{int(value):,}",
        "sparkline": _daily_values(rows, "orders"),
        "prior_week": prior_value,
        "change_pct": _pct_change(value, prior_value),
    }


def _resolve_conversion_rate_7d(db: Session) -> dict[str, Any]:
    rows = _trailing_kpi_rows(db)
    prior = _prior_kpi_rows(db)
    avg = _avg_attr(rows, "conversion_rate")
    prior_avg = _avg_attr(prior, "conversion_rate")
    return {
        "value": avg or 0.0,
        "display_value": f"{(avg or 0.0):.2f}%",
        "sparkline": _daily_values(rows, "conversion_rate"),
        "prior_week": prior_avg,
        "change_pct": _pct_change(avg, prior_avg),
    }


def _resolve_sessions_7d(db: Session) -> dict[str, Any]:
    rows = _trailing_kpi_rows(db)
    prior = _prior_kpi_rows(db)
    value = _sum_attr(rows, "sessions")
    prior_value = _sum_attr(prior, "sessions")
    return {
        "value": value,
        "display_value": f"{int(value):,}",
        "sparkline": _daily_values(rows, "sessions"),
        "prior_week": prior_value,
        "change_pct": _pct_change(value, prior_value),
    }


def _resolve_ad_spend_7d(db: Session) -> dict[str, Any]:
    rows = _trailing_kpi_rows(db)
    prior = _prior_kpi_rows(db)
    value = _sum_attr(rows, "ad_spend")
    prior_value = _sum_attr(prior, "ad_spend")
    return {
        "value": value,
        "display_value": f"${value/1000:.1f}k" if value < 1_000_000 else f"${value/1_000_000:.2f}M",
        "sparkline": _daily_values(rows, "ad_spend"),
        "prior_week": prior_value,
        "change_pct": _pct_change(value, prior_value),
    }


def _resolve_mer_7d(db: Session) -> dict[str, Any]:
    rows = _trailing_kpi_rows(db)
    prior = _prior_kpi_rows(db)
    rev = _sum_attr(rows, "revenue")
    spend = _sum_attr(rows, "ad_spend")
    mer = rev / spend if spend else 0.0
    prior_rev = _sum_attr(prior, "revenue")
    prior_spend = _sum_attr(prior, "ad_spend")
    prior_mer = prior_rev / prior_spend if prior_spend else None
    spark = [(float(r.revenue or 0) / float(r.ad_spend)) if r.ad_spend else 0.0 for r in rows]
    return {
        "value": mer,
        "display_value": f"{mer:.2f}x",
        "sparkline": spark,
        "prior_week": prior_mer,
        "change_pct": _pct_change(mer, prior_mer),
    }


def _resolve_cost_per_purchase_7d(db: Session) -> dict[str, Any]:
    rows = _trailing_kpi_rows(db)
    prior = _prior_kpi_rows(db)
    spend = _sum_attr(rows, "ad_spend")
    orders = _sum_attr(rows, "orders")
    cpp = spend / orders if orders else 0.0
    prior_spend = _sum_attr(prior, "ad_spend")
    prior_orders = _sum_attr(prior, "orders")
    prior_cpp = prior_spend / prior_orders if prior_orders else None
    return {
        "value": cpp,
        "display_value": f"${cpp:.2f}",
        "sparkline": [(float(r.ad_spend or 0) / (r.orders or 1)) if r.orders else 0.0 for r in rows],
        "prior_week": prior_cpp,
        "change_pct": _pct_change(cpp, prior_cpp),
    }


def _resolve_tickets_created_7d(db: Session) -> dict[str, Any]:
    rows = _trailing_kpi_rows(db)
    prior = _prior_kpi_rows(db)
    value = _sum_attr(rows, "tickets_created")
    prior_value = _sum_attr(prior, "tickets_created")
    return {
        "value": value,
        "display_value": f"{int(value):,}",
        "sparkline": _daily_values(rows, "tickets_created"),
        "prior_week": prior_value,
        "change_pct": _pct_change(value, prior_value),
    }


def _resolve_first_response_hours_7d(db: Session) -> dict[str, Any]:
    rows = _trailing_kpi_rows(db)
    prior = _prior_kpi_rows(db)
    avg = _avg_attr(rows, "first_response_time")
    prior_avg = _avg_attr(prior, "first_response_time")
    return {
        "value": avg or 0.0,
        "display_value": f"{(avg or 0.0):.1f}h",
        "sparkline": _daily_values(rows, "first_response_time"),
        "prior_week": prior_avg,
        "change_pct": _pct_change(avg, prior_avg),
    }


def _resolve_resolution_hours_7d(db: Session) -> dict[str, Any]:
    rows = _trailing_kpi_rows(db)
    prior = _prior_kpi_rows(db)
    avg = _avg_attr(rows, "resolution_time")
    prior_avg = _avg_attr(prior, "resolution_time")
    return {
        "value": avg or 0.0,
        "display_value": f"{(avg or 0.0):.1f}h",
        "sparkline": _daily_values(rows, "resolution_time"),
        "prior_week": prior_avg,
        "change_pct": _pct_change(avg, prior_avg),
    }


def _resolve_csat_7d(db: Session) -> dict[str, Any]:
    rows = _trailing_kpi_rows(db)
    prior = _prior_kpi_rows(db)
    avg = _avg_attr(rows, "csat")
    prior_avg = _avg_attr(prior, "csat")
    return {
        "value": avg or 0.0,
        "display_value": f"{(avg or 0.0):.2f}",
        "sparkline": _daily_values(rows, "csat"),
        "prior_week": prior_avg,
        "change_pct": _pct_change(avg, prior_avg),
    }


def _resolve_sla_breach_rate_7d(db: Session) -> dict[str, Any]:
    rows = _trailing_kpi_rows(db)
    prior = _prior_kpi_rows(db)
    avg = _avg_attr(rows, "sla_breach_rate")
    prior_avg = _avg_attr(prior, "sla_breach_rate")
    return {
        "value": avg or 0.0,
        "display_value": f"{(avg or 0.0):.1f}%",
        "sparkline": _daily_values(rows, "sla_breach_rate"),
        "prior_week": prior_avg,
        "change_pct": _pct_change(avg, prior_avg),
    }


def _resolve_open_backlog_now(db: Session) -> dict[str, Any]:
    rows = _trailing_kpi_rows(db)
    prior = _prior_kpi_rows(db)
    value = float(rows[-1].open_backlog or 0) if rows else 0.0
    prior_value = _avg_attr(prior, "open_backlog")
    return {
        "value": value,
        "display_value": f"{int(value):,}",
        "sparkline": _daily_values(rows, "open_backlog"),
        "prior_week": prior_value,
        "change_pct": _pct_change(value, prior_value),
    }


def _resolve_tickets_per_100_orders_7d(db: Session) -> dict[str, Any]:
    rows = _trailing_kpi_rows(db)
    prior = _prior_kpi_rows(db)
    tickets = _sum_attr(rows, "tickets_created")
    orders = _sum_attr(rows, "orders")
    ratio = (tickets / orders * 100) if orders else 0.0
    prior_tickets = _sum_attr(prior, "tickets_created")
    prior_orders = _sum_attr(prior, "orders")
    prior_ratio = (prior_tickets / prior_orders * 100) if prior_orders else None
    return {
        "value": ratio,
        "display_value": f"{ratio:.1f}",
        "sparkline": [((float(r.tickets_created or 0) / (r.orders or 1)) * 100) if r.orders else 0.0 for r in rows],
        "prior_week": prior_ratio,
        "change_pct": _pct_change(ratio, prior_ratio),
    }


# ── fleet / telemetry ───────────────────────────────────────────────────

def _resolve_fleet_active_now(db: Session) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=30)
    count = db.execute(
        select(func.count(func.distinct(TelemetryStreamEvent.device_id))).where(
            TelemetryStreamEvent.sample_timestamp >= cutoff
        )
    ).scalar() or 0
    # 7-day rolling daily active as sparkline
    daily_rows = db.execute(
        select(TelemetryDaily.business_date, TelemetryDaily.connected_users)
        .where(TelemetryDaily.business_date >= (date.today() - timedelta(days=8)))
        .order_by(TelemetryDaily.business_date)
    ).all()
    spark = [float(r[1] or 0) for r in daily_rows]
    return {
        "value": float(count),
        "display_value": f"{int(count):,}",
        "sparkline": spark,
        "prior_week": None,
        "change_pct": None,
    }


def _resolve_cook_success_rate_7d(db: Session) -> dict[str, Any]:
    rows = db.execute(
        select(TelemetryDaily).where(
            TelemetryDaily.business_date >= (date.today() - timedelta(days=8))
        ).order_by(TelemetryDaily.business_date)
    ).scalars().all()
    avg = _avg_attr(rows, "cook_success_rate")
    return {
        "value": (avg or 0.0),
        "display_value": f"{((avg or 0.0) * 100):.1f}%" if (avg or 0.0) <= 1 else f"{(avg or 0.0):.1f}%",
        "sparkline": _daily_values(rows, "cook_success_rate"),
        "prior_week": None,
        "change_pct": None,
    }


def _resolve_disconnect_rate_7d(db: Session) -> dict[str, Any]:
    """Disconnects-per-session over the last 7 days, computed live from
    TelemetrySession (the same source cache_builders.py and firmware.py
    use). Previously this resolver read from TelemetryDaily.disconnect_rate,
    which has been a dead cache since 2025-06-20 (every row 0.0). The
    Command Center gauge stuck at 0% as a result; Joseph flagged it
    2026-04-29.

    Headline value: SUM(disconnect_events) / COUNT(sessions). Same
    convention as the recommendations engine (>12% triggers an alert).

    Sparkline: per-day disconnects-per-session for the last 8 days.
    Days with zero sessions render as 0 — better than gaps for the
    sparkline visualization.
    """
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=7)

    headline = db.execute(
        select(
            func.count(TelemetrySession.id).label("sessions"),
            func.coalesce(func.sum(TelemetrySession.disconnect_events), 0).label("disconnects"),
        ).where(
            TelemetrySession.session_start >= start_dt,
            TelemetrySession.session_start < end_dt,
        )
    ).one()
    sessions = int(headline.sessions or 0)
    disconnects = int(headline.disconnects or 0)
    rate = (disconnects / sessions) if sessions else 0.0

    # Per-day sparkline (last 8 daily buckets).
    daily_rows = db.execute(
        select(
            func.date_trunc("day", TelemetrySession.session_start).label("d"),
            func.count(TelemetrySession.id).label("s"),
            func.coalesce(func.sum(TelemetrySession.disconnect_events), 0).label("dc"),
        ).where(
            TelemetrySession.session_start >= end_dt - timedelta(days=8),
            TelemetrySession.session_start < end_dt,
        ).group_by("d").order_by("d")
    ).all()
    sparkline = [
        (float(r.dc) / float(r.s)) if r.s else 0.0
        for r in daily_rows
    ]

    return {
        "value": rate,
        "display_value": f"{(rate * 100):.1f}%",
        "sparkline": sparkline,
        "prior_week": None,
        "change_pct": None,
    }


def _resolve_drafts_awaiting(db: Session) -> dict[str, Any]:
    value = db.execute(
        select(func.count(DeciDecision.id)).where(DeciDecision.status == "draft")
    ).scalar() or 0
    return {
        "value": float(value),
        "display_value": f"{int(value)}",
        "sparkline": [float(value)] * 7,
        "prior_week": None,
        "change_pct": None,
    }


# ── registry ────────────────────────────────────────────────────────────

CATALOG: dict[str, MetricMeta] = {
    "revenue_7d": MetricMeta(
        key="revenue_7d", label="Revenue (7d)", unit="$", category="commerce",
        direction="higher_better",
        description="Rolling 7-day Shopify net revenue. North star when growth is the focus.",
        default_band=(None, None),
        drill_href="/revenue",
        resolver=_resolve_revenue_7d,
    ),
    "aov_7d": MetricMeta(
        key="aov_7d", label="AOV", unit="$", category="commerce",
        direction="higher_better",
        description="Average order value over trailing 7 days. Early signal for basket-builder impact.",
        default_band=(None, None),
        drill_href="/revenue",
        resolver=_resolve_aov_7d,
    ),
    "orders_7d": MetricMeta(
        key="orders_7d", label="Orders (7d)", unit="count", category="commerce",
        direction="higher_better",
        description="Rolling 7-day Shopify order count. Good when unit velocity matters more than revenue.",
        default_band=(None, None),
        drill_href="/revenue",
        resolver=_resolve_orders_7d,
    ),
    "conversion_rate_7d": MetricMeta(
        key="conversion_rate_7d", label="Conversion rate", unit="%", category="commerce",
        direction="higher_better",
        description="Shopify session→order conversion, 7d average. Sensitive to PDP, checkout, and offer changes.",
        default_band=(None, None),
        drill_href="/revenue",
        resolver=_resolve_conversion_rate_7d,
    ),
    "sessions_7d": MetricMeta(
        key="sessions_7d", label="Sessions (7d)", unit="count", category="commerce",
        direction="higher_better",
        description="Rolling 7-day site sessions. Proxy for top-of-funnel demand.",
        default_band=(None, None),
        drill_href="/revenue",
        resolver=_resolve_sessions_7d,
    ),
    "ad_spend_7d": MetricMeta(
        key="ad_spend_7d", label="Ad spend (7d)", unit="$", category="marketing",
        direction="target",
        description="Rolling 7-day TripleWhale ad spend across all channels. Pair with MER.",
        default_band=(None, None),
        drill_href="/division/marketing",
        resolver=_resolve_ad_spend_7d,
    ),
    "mer_7d": MetricMeta(
        key="mer_7d", label="MER (7d)", unit="ratio", category="marketing",
        direction="higher_better",
        description="Marketing Efficiency Ratio = revenue / ad spend (7d). Core profitability signal.",
        default_band=(1.5, None),
        default_target=2.0,
        drill_href="/division/marketing",
        resolver=_resolve_mer_7d,
    ),
    "cost_per_purchase_7d": MetricMeta(
        key="cost_per_purchase_7d", label="Cost per purchase", unit="$", category="marketing",
        direction="lower_better",
        description="Blended CAC over 7 days. Watch when scaling spend or reshuffling channel mix.",
        default_band=(None, None),
        drill_href="/division/marketing",
        resolver=_resolve_cost_per_purchase_7d,
    ),
    "tickets_created_7d": MetricMeta(
        key="tickets_created_7d", label="Tickets (7d)", unit="count", category="cx",
        direction="lower_better",
        description="Rolling 7-day Freshdesk inbound ticket count. Rising volume usually leads a CX crisis.",
        default_band=(None, None),
        drill_href="/division/customer-experience",
        resolver=_resolve_tickets_created_7d,
    ),
    "first_response_hours_7d": MetricMeta(
        key="first_response_hours_7d", label="First response", unit="hours", category="cx",
        direction="lower_better",
        description="Freshdesk average first-response time, 7d. SLA proxy.",
        default_band=(None, 4.0),
        default_target=2.0,
        drill_href="/division/customer-experience",
        resolver=_resolve_first_response_hours_7d,
    ),
    "resolution_hours_7d": MetricMeta(
        key="resolution_hours_7d", label="Resolution time", unit="hours", category="cx",
        direction="lower_better",
        description="Freshdesk average resolution hours, 7d. Long-tail customer-effort signal.",
        default_band=(None, 48.0),
        drill_href="/division/customer-experience",
        resolver=_resolve_resolution_hours_7d,
    ),
    "csat_7d": MetricMeta(
        key="csat_7d", label="CSAT", unit="score", category="cx",
        direction="higher_better",
        description="Freshdesk CSAT 7d average (0–100). Direct customer sentiment readout.",
        default_band=(85.0, None),
        default_target=95.0,
        drill_href="/division/customer-experience",
        resolver=_resolve_csat_7d,
    ),
    "sla_breach_rate_7d": MetricMeta(
        key="sla_breach_rate_7d", label="SLA breach rate", unit="%", category="cx",
        direction="lower_better",
        description="Share of tickets that breached SLA in the last 7d. Escalates fast when CX capacity is thin.",
        default_band=(None, 5.0),
        drill_href="/division/customer-experience",
        resolver=_resolve_sla_breach_rate_7d,
    ),
    "open_backlog_now": MetricMeta(
        key="open_backlog_now", label="Open backlog", unit="count", category="cx",
        direction="lower_better",
        description="Currently open Freshdesk tickets. Spikes when CX gets underwater.",
        default_band=(None, None),
        drill_href="/division/customer-experience",
        resolver=_resolve_open_backlog_now,
    ),
    "tickets_per_100_orders_7d": MetricMeta(
        key="tickets_per_100_orders_7d", label="Tickets / 100 orders", unit="ratio", category="cx",
        direction="lower_better",
        description="Support intensity normalized by sales volume. Rising ratio = a product or process issue, not just busy week.",
        default_band=(None, 8.0),
        drill_href="/division/customer-experience",
        resolver=_resolve_tickets_per_100_orders_7d,
    ),
    "fleet_active_now": MetricMeta(
        key="fleet_active_now", label="Active controllers", unit="count", category="fleet",
        direction="higher_better",
        description="Venoms reporting in the last 30 minutes. Real-time fleet reach.",
        default_band=(None, None),
        drill_href="/division/product-engineering/firmware",
        resolver=_resolve_fleet_active_now,
    ),
    "cook_success_rate_7d": MetricMeta(
        key="cook_success_rate_7d", label="Cook success rate", unit="%", category="fleet",
        direction="higher_better",
        description="% of cooks that reached target, stayed stable, no errors (7d). Product-quality telemetry.",
        default_band=(0.85, None),
        default_target=0.92,
        drill_href="/division/product-engineering/firmware",
        resolver=_resolve_cook_success_rate_7d,
    ),
    "disconnect_rate_7d": MetricMeta(
        key="disconnect_rate_7d", label="Disconnect rate", unit="%", category="fleet",
        direction="lower_better",
        description="Disconnect events per session (7d, expressed as a percent — 5% = 5 disconnects per 100 sessions). WiFi/AWS reliability gauge.",
        default_band=(None, 0.10),
        drill_href="/division/product-engineering/firmware",
        resolver=_resolve_disconnect_rate_7d,
    ),
    "drafts_awaiting_decision": MetricMeta(
        key="drafts_awaiting_decision", label="DECI drafts", unit="count", category="ops",
        direction="lower_better",
        description="Open DECI decision drafts waiting for a human call. Pile-up = leadership bottleneck.",
        default_band=(None, 5.0),
        drill_href="/deci",
        resolver=_resolve_drafts_awaiting,
    ),
}


def list_catalog_for_prompt() -> list[dict[str, Any]]:
    """Compact catalog shape that goes into the Opus selection prompt."""
    return [
        {
            "key": m.key,
            "label": m.label,
            "unit": m.unit,
            "category": m.category,
            "direction": m.direction,
            "description": m.description,
            "default_target": m.default_target,
        }
        for m in CATALOG.values()
    ]


def resolve_metric(db: Session, key: str) -> Optional[dict[str, Any]]:
    meta = CATALOG.get(key)
    if meta is None or meta.resolver is None:
        return None
    try:
        return meta.resolver(db)
    except Exception as e:
        return {
            "value": 0.0,
            "display_value": "—",
            "sparkline": [],
            "prior_week": None,
            "change_pct": None,
            "error": str(e),
        }
