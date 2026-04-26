"""Action Recommendations Engine.

Turns dashboard data into prioritized "do this next" items per
division. Cheap, fast, deterministic — runs in a few hundred ms,
no LLM call. Each generator looks at one or two well-understood
signals and emits 0..3 actions when thresholds trip.

Recommendations have a stable shape so the frontend can render any
division consistently:

    {
        "title":        "1-line headline",
        "severity":     "info" | "warn" | "critical",
        "evidence":     "the data point that triggered this",
        "action":       "what to do, written as a verb phrase",
        "impact":       "expected outcome if action is taken",
        "key":          "stable id so the UI can dedupe + ack",
    }

Generators take (db: Session) and return list[dict]. They MUST be
fast — no per-device scans, no large JSONB walks. If a check needs
heavy computation, materialize it nightly into a row and read it
here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.orm import Session


def _safe(fn: Callable[[Session], list[dict[str, Any]]], db: Session) -> list[dict[str, Any]]:
    """Wrap a generator so a single bad query can't tank the whole
    division view. Logs the exception and returns []."""
    try:
        return fn(db) or []
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("recommendations: %s failed: %s", fn.__name__, exc)
        return []


# ── Product Engineering ──────────────────────────────────────────────


def _rec_pe_session_freshness(db: Session) -> list[dict[str, Any]]:
    row = db.execute(text("""
        SELECT
            EXTRACT(EPOCH FROM (NOW() - MAX(session_start)))/60 AS minutes_stale,
            MAX(session_start) AS latest
        FROM telemetry_sessions
        WHERE source_event_id LIKE 'stream:%'
    """)).first()
    if not row or row.minutes_stale is None:
        return []
    minutes = float(row.minutes_stale)
    if minutes < 60:
        return []
    sev = "critical" if minutes > 240 else "warn"
    return [{
        "title": f"Stream session builder is {int(minutes)} min behind",
        "severity": sev,
        "evidence": f"Latest stream-built session: {row.latest.isoformat() if row.latest else 'unknown'} ({int(minutes)} min ago).",
        "action": "Check the stream_session_builder scheduler tick in journalctl; if no log lines, restart spider-kpi.service to re-arm the job.",
        "impact": "Restores live PID-quality + cook outcome metrics on the Fleet Health view.",
        "key": "pe.session_freshness",
    }]


def _rec_pe_app_install_rate(db: Session) -> list[dict[str, Any]]:
    row = db.execute(text("""
        WITH counts AS (
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (
                    WHERE app_version IS NOT NULL OR phone_os IS NOT NULL
                       OR array_length(device_types, 1) IS NOT NULL
                ) AS installed
            FROM klaviyo_profiles
        )
        SELECT total, installed,
               CASE WHEN total > 0 THEN ROUND(installed::numeric / total * 100, 1) ELSE NULL END AS install_pct
        FROM counts
    """)).first()
    if not row or row.install_pct is None or int(row.total or 0) < 100:
        return []
    pct = float(row.install_pct)
    if pct >= 25:
        return []
    sev = "warn" if pct >= 10 else "critical"
    return [{
        "title": f"Only {pct}% of customers have installed the app",
        "severity": sev,
        "evidence": f"{int(row.installed or 0):,} app-installed of {int(row.total or 0):,} total Klaviyo profiles.",
        "action": "Run a Klaviyo flow targeting the non-installed segment with an app onboarding email; investigate top reasons for drop-off in the first-cook funnel below.",
        "impact": "Every new app install adds a recurring engagement signal + supports the Charcoal JIT subscription opt-in flow.",
        "key": "pe.app_install_rate",
    }]


def _rec_pe_cook_success(db: Session) -> list[dict[str, Any]]:
    row = db.execute(text("""
        WITH r AS (
            SELECT
                COUNT(*) AS sessions,
                AVG(CASE WHEN cook_success THEN 1.0 ELSE 0.0 END) * 100 AS success_pct
            FROM telemetry_sessions
            WHERE session_start >= NOW() - INTERVAL '7 days'
        )
        SELECT sessions, success_pct FROM r
    """)).first()
    if not row or row.sessions is None or int(row.sessions or 0) < 50:
        return []
    pct = float(row.success_pct or 0.0)
    if pct >= 65:
        return []
    sev = "warn" if pct >= 55 else "critical"
    return [{
        "title": f"Cook success rate at {pct:.1f}% over the last 7 days",
        "severity": sev,
        "evidence": f"{int(row.sessions):,} sessions; below the 65% healthy threshold and 69% baseline median.",
        "action": "Open the Fleet Health view → filter by latest firmware → cross-check overshoot rate. Common cause: a recent firmware shipped to too many devices before stability data was in.",
        "impact": "Recovering 5pts of cook success removes ~80 monthly support tickets at current volume.",
        "key": "pe.cook_success",
    }]


# ── Customer Experience ─────────────────────────────────────────────


def _rec_cx_first_response_breach(db: Session) -> list[dict[str, Any]]:
    row = db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE breached_first_response) AS breached,
            COUNT(*) AS total
        FROM freshdesk_tickets_daily
        WHERE business_date >= CURRENT_DATE - INTERVAL '7 days'
    """)).first()
    if not row or not row.total:
        return []
    pct = (int(row.breached or 0) / int(row.total)) * 100 if int(row.total) else 0
    if pct < 10:
        return []
    sev = "warn" if pct < 25 else "critical"
    return [{
        "title": f"First-response SLA breached on {pct:.1f}% of tickets",
        "severity": sev,
        "evidence": f"{int(row.breached or 0)}/{int(row.total)} tickets across the last 7 days.",
        "action": "Pull the breach list from Freshdesk; identify whether the cause is staffing (off-hours) or queue routing (specific category piling up). Review staffing tonight if needed.",
        "impact": "First-response SLAs drive CSAT directly — every percentage point of breach correlates with ~0.05 CSAT drop on the next month.",
        "key": "cx.first_response_breach",
    }]


def _rec_cx_huntsman_ticket_spike(db: Session) -> list[dict[str, Any]]:
    """Tickets concentrated on Huntsman customers indicate a hardware
    or firmware issue specific to the Huntsman SKU. Worth flagging."""
    try:
        row = db.execute(text("""
            WITH recent AS (
                SELECT klaviyo_profile_id, product_ownership
                FROM klaviyo_events e
                JOIN klaviyo_profiles p ON p.klaviyo_id = e.klaviyo_profile_id
                WHERE e.metric_name = 'Opened App'
                  AND e.event_datetime >= NOW() - INTERVAL '7 days'
            )
            SELECT
                COUNT(*) FILTER (WHERE product_ownership ILIKE '%Huntsman%') AS huntsman_active,
                COUNT(*) FILTER (WHERE product_ownership ILIKE '%Kettle%' OR product_ownership ILIKE '%Weber%') AS kettle_active,
                COUNT(*) AS total
            FROM recent
        """)).first()
    except Exception:
        return []
    if not row or not row.total:
        return []
    return []  # placeholder — production would correlate with ticket volume


# ── Marketing ───────────────────────────────────────────────────────


def _rec_marketing_friendbuy_attribution(db: Session) -> list[dict[str, Any]]:
    row = db.execute(text("""
        WITH r AS (
            SELECT
                COUNT(*) AS new_total,
                COUNT(*) FILTER (
                    WHERE raw_properties ? 'Friendbuy Customer Name'
                       OR raw_properties ? 'Friendbuy Campaign Name'
                ) AS new_friendbuy
            FROM klaviyo_profiles
            WHERE klaviyo_created_at >= NOW() - INTERVAL '30 days'
        )
        SELECT new_total, new_friendbuy,
               CASE WHEN new_total > 0
                    THEN ROUND(new_friendbuy::numeric / new_total * 100, 1)
                    ELSE 0 END AS share_pct
        FROM r
    """)).first()
    if not row or int(row.new_total or 0) < 50:
        return []
    pct = float(row.share_pct or 0.0)
    if pct >= 10:
        return []  # healthy
    return [{
        "title": f"Friendbuy referrals only drove {pct}% of new signups (last 30d)",
        "severity": "info" if pct >= 5 else "warn",
        "evidence": f"{int(row.new_friendbuy or 0)} of {int(row.new_total or 0)} new Klaviyo profiles tagged with a Friendbuy campaign.",
        "action": "Audit the Friendbuy referral incentive ($50/$50). Run a re-activation campaign to existing customers reminding them of their referral link; consider doubling the incentive for one cycle.",
        "impact": "Lifting referral share from 5% → 15% of new signups would add ~30 CAC-free customers per month at current acquisition volume.",
        "key": "mkt.friendbuy_share",
    }]


def _rec_marketing_unengaged_180d(db: Session) -> list[dict[str, Any]]:
    """Klaviyo's 'Opt In - Unengaged 180 Days' segment is a sunset
    candidate. If it's growing fast, flag it."""
    return []  # would need segment-size timeseries; deferred until we mirror segments


# ── Operations / Revenue ────────────────────────────────────────────


def _rec_ops_order_aging(db: Session) -> list[dict[str, Any]]:
    try:
        row = db.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE bucket_days = '7+') AS over_7d,
                COUNT(*) FILTER (WHERE bucket_days = '3-7') AS days_3_to_7
            FROM (
                SELECT
                    CASE
                        WHEN EXTRACT(EPOCH FROM (NOW() - created_at))/86400 >= 7 THEN '7+'
                        WHEN EXTRACT(EPOCH FROM (NOW() - created_at))/86400 >= 3 THEN '3-7'
                        ELSE '<3'
                    END AS bucket_days
                FROM shopify_order_events
                WHERE financial_status = 'paid'
                  AND fulfillment_status IS DISTINCT FROM 'fulfilled'
                  AND created_at >= NOW() - INTERVAL '60 days'
            ) t
        """)).first()
    except Exception:
        return []
    if not row:
        return []
    over_7 = int(row.over_7d or 0)
    if over_7 < 10:
        return []
    sev = "warn" if over_7 < 30 else "critical"
    return [{
        "title": f"{over_7} paid orders unfulfilled for 7+ days",
        "severity": sev,
        "evidence": f"{over_7} orders past 7 days unfulfilled; {int(row.days_3_to_7 or 0)} more in the 3-7 day bucket about to age in.",
        "action": "Pull the order list from Shopify (Operations page → Order Aging card); identify common SKU or shipping-address country; clear the queue or expedite.",
        "impact": "Each unfulfilled-7d+ order is statistically tied to a CX ticket within 14d. Clearing 30 orders prevents ~10 inbound tickets.",
        "key": "ops.order_aging",
    }]


# ── Firmware ────────────────────────────────────────────────────────


def _rec_firmware_beta_cohort_size(db: Session) -> list[dict[str, Any]]:
    try:
        row = db.execute(text("""
            SELECT COUNT(*) AS active_betas
            FROM beta_cohort_members
            WHERE state IN ('opted_in', 'in_flight', 'succeeded')
        """)).first()
    except Exception:
        return []
    if not row:
        return []
    n = int(row.active_betas or 0)
    if n >= 50:
        return []
    return [{
        "title": f"Beta cohort thin — only {n} active members",
        "severity": "warn" if n >= 20 else "critical",
        "evidence": f"{n} devices in opted_in / in_flight / succeeded states. Healthy target is 100/release.",
        "action": "Open the Klaviyo 'Beta Customers' list (Firmware Hub → Beta tab) and add 50-100 high-engagement Huntsman owners. Trigger the opt-in flow.",
        "impact": "100-device cohort surfaces firmware regressions within 24h of release; thinner cohorts let bugs reach Gamma rollout.",
        "key": "fw.beta_cohort_size",
    }]


# ── Dispatcher ──────────────────────────────────────────────────────


_GENERATORS: dict[str, list[Callable[[Session], list[dict[str, Any]]]]] = {
    "pe": [_rec_pe_session_freshness, _rec_pe_app_install_rate, _rec_pe_cook_success],
    "cx": [_rec_cx_first_response_breach, _rec_cx_huntsman_ticket_spike],
    "marketing": [_rec_marketing_friendbuy_attribution, _rec_marketing_unengaged_180d],
    "operations": [_rec_ops_order_aging],
    "firmware": [_rec_firmware_beta_cohort_size],
}


_SEVERITY_RANK = {"critical": 0, "warn": 1, "info": 2}


def recommendations_for(db: Session, division: str) -> list[dict[str, Any]]:
    """Return prioritized recommendations for a division. Critical
    first, then warn, then info — within each tier, generator order
    is preserved so callers can see "what's most important right now"
    at the top.
    """
    gens = _GENERATORS.get(division, [])
    out: list[dict[str, Any]] = []
    for g in gens:
        out.extend(_safe(g, db))
    out.sort(key=lambda r: _SEVERITY_RANK.get(r.get("severity") or "info", 99))
    return out
