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
    division view. Logs the exception and rolls back so the next
    generator's queries don't fail with InFailedSqlTransaction.

    Without the rollback, one bad recommendation poisons the entire
    SQLAlchemy session — every subsequent rec query in the same
    request fails with `current transaction is aborted, commands
    ignored until end of transaction block`. That cascade is what
    surfaced as /api/cx/snapshot timeouts on 2026-04-28.
    """
    try:
        return fn(db) or []
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("recommendations: %s failed: %s", fn.__name__, exc)
        # SQLAlchemy 2.0 leaves the session in an aborted state after
        # a query error. rollback() clears the transaction; expire_all
        # drops cached identities so the next generator sees fresh data.
        # Do NOT close() — the session is request-scoped (FastAPI
        # Depends), and closing it here breaks every generator after.
        try:
            db.rollback()
        except Exception:
            pass
        try:
            db.expire_all()
        except Exception:
            pass
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
    """App install rate of OWNERS — not the whole audience.

    Joseph's 2026-04-26 note: dividing app users by total Klaviyo
    profiles is misleading because the audience includes 36k+
    newsletter signups who don't own a Spider product. The honest
    comparison is owners (people we sold to) vs app users (people
    using the app to control their grill).
    """
    from app.services.klaviyo_audience import (
        count_app_users, count_owners, count_connected_devices,
    )
    owners_total = count_owners(db).get("total", 0)
    app_users = count_app_users(db)
    devices = count_connected_devices(db).get("lifetime", 0)
    if owners_total < 100 or app_users < 1:
        return []
    pct_of_owners = round(app_users / owners_total * 100, 1) if owners_total else 0
    # Devices is the more authoritative "real fleet" denominator,
    # since every connected device implies an app user at some point.
    pct_of_devices = round(app_users / devices * 100, 1) if devices else 0
    if pct_of_devices >= 60:
        return []
    sev = "warn" if pct_of_devices >= 35 else "critical"
    return [{
        "title": f"Only {pct_of_devices}% of connected devices have an active app user",
        "severity": sev,
        "evidence": (
            f"{app_users:,} profiles ever fired Opened App vs {devices:,} unique devices "
            f"that have ever connected to AWS. Gap of {max(0, devices - app_users):,} devices."
        ),
        "action": (
            "Targeted re-engagement: pull the device-MAC ↔ Klaviyo-profile bridge for owners "
            "without a recent Opened App event; send a flow inviting them back into the app. "
            "Pre-2025 users won't have an Opened App event because the SDK was added in mid-2025 — "
            "that subset is fixable only by getting them to open the app once."
        ),
        "impact": "Every recovered app user unlocks Charcoal JIT, beta cohort eligibility, and recurring engagement signal.",
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
    # freshdesk_tickets_daily exposes `sla_breach_rate` (0..1) and
    # `tickets_created` per business_date — no per-row breach flag.
    # Approximate breach count = sum(tickets_created * sla_breach_rate).
    # Earlier version of this query referenced `breached_first_response`
    # which never existed in this schema; that failure poisoned the
    # SQLAlchemy session and cascaded into CX snapshot timeouts.
    row = db.execute(text("""
        SELECT
            COALESCE(SUM(tickets_created * sla_breach_rate), 0)::int AS breached,
            COALESCE(SUM(tickets_created), 0) AS total
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


def _rec_pe_disconnect_rate(db: Session) -> list[dict[str, Any]]:
    """High disconnect rate signals a wifi/connectivity issue across
    the fleet — could be an AWS endpoint regression or a firmware
    regression in the connection retry logic."""
    row = db.execute(text("""
        SELECT
            COUNT(*) AS sessions,
            AVG(CASE WHEN disconnect_events > 0 THEN 1.0 ELSE 0.0 END) * 100 AS disconnect_pct
        FROM telemetry_sessions
        WHERE session_start >= NOW() - INTERVAL '7 days'
          AND session_duration_seconds >= 600
    """)).first()
    if not row or int(row.sessions or 0) < 50:
        return []
    pct = float(row.disconnect_pct or 0.0)
    if pct < 8:
        return []
    sev = "warn" if pct < 15 else "critical"
    return [{
        "title": f"Disconnect rate at {pct:.1f}% of sessions (7d)",
        "severity": sev,
        "evidence": f"{int(row.sessions):,} sessions ≥10 min in last 7d; healthy threshold is ≤5%.",
        "action": "Check AWS IoT endpoint health for the affected region; cross-reference with the firmware version distribution to see if a recent OTA correlates.",
        "impact": "Disconnects break cooks mid-session. Each percentage point drop is ~25 inbound CX tickets/month.",
        "key": "pe.disconnect_rate",
    }]


def _rec_pe_overshoot_rate(db: Session) -> list[dict[str, Any]]:
    """Overshoot signals PID tuning regression — typically from a
    firmware change that nudged the control constants."""
    row = db.execute(text("""
        SELECT
            COUNT(*) AS sessions,
            AVG(CASE WHEN max_overshoot_f >= 25 THEN 1.0 ELSE 0.0 END) * 100 AS overshoot_pct
        FROM telemetry_sessions
        WHERE session_start >= NOW() - INTERVAL '7 days'
          AND target_temp IS NOT NULL
          AND max_overshoot_f IS NOT NULL
    """)).first()
    if not row or int(row.sessions or 0) < 50:
        return []
    pct = float(row.overshoot_pct or 0.0)
    if pct < 18:
        return []
    sev = "warn" if pct < 28 else "critical"
    return [{
        "title": f"{pct:.1f}% of cooks overshot target by ≥25°F (7d)",
        "severity": sev,
        "evidence": f"{int(row.sessions):,} sessions with target temp set; baseline overshoot rate is ~12-15%.",
        "action": "Filter Fleet Control Health by latest firmware version and overshoot = ≥25°F; if concentrated on one fw, ECR a PID-tuning fix.",
        "impact": "Overshoot causes burnt food and the highest-frustration CX tickets. Recovering from 25% → 15% overshoot saves ~40 tickets/month.",
        "key": "pe.overshoot_rate",
    }]


def _rec_cx_backlog_growing(db: Session) -> list[dict[str, Any]]:
    """Detect ticket backlog growing 3 days in a row — a leading
    indicator of CX team capacity falling behind inbound volume.

    Uses `unresolved_tickets` (the real column on the daily roll-up
    table). Earlier version of this query referenced `open_tickets_eod`
    which never existed in this schema; that failure poisoned the
    SQLAlchemy session and was the second contributor to CX snapshot
    cascade timeouts on 2026-04-28."""
    rows = db.execute(text("""
        SELECT business_date, unresolved_tickets
        FROM freshdesk_tickets_daily
        WHERE business_date >= CURRENT_DATE - INTERVAL '5 days'
        ORDER BY business_date DESC
        LIMIT 5
    """)).all()
    if len(rows) < 4:
        return []
    sequence = [int(r.unresolved_tickets or 0) for r in rows]
    if not all(sequence[i] > sequence[i + 1] for i in range(3)):
        return []
    delta = sequence[0] - sequence[3]
    return [{
        "title": f"CX backlog growing 4 days straight (+{delta} tickets)",
        "severity": "warn" if delta < 50 else "critical",
        "evidence": f"Open tickets EOD: {' → '.join(str(s) for s in reversed(sequence[:4]))}.",
        "action": "Look at ticket category mix today vs 7d-prior — if a single category jumped, that's likely a product/firmware regression. Otherwise consider routing or staffing.",
        "impact": "Backlogs erode CSAT lagging-indicators by 0.1-0.2 per week of growth.",
        "key": "cx.backlog_growth",
    }]


def _rec_marketing_unengaged_share(db: Session) -> list[dict[str, Any]]:
    """High share of audience profiles dormant 90d+. Audience-level
    metric (not owners) since this drives email-list health and
    Klaviyo billing. Owners get their own re-engagement track in
    pe.app_install_rate."""
    row = db.execute(text("""
        WITH counts AS (
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (
                    WHERE last_event_at IS NOT NULL
                      AND last_event_at < NOW() - INTERVAL '90 days'
                ) AS dormant_90d
            FROM klaviyo_profiles
        )
        SELECT total, dormant_90d,
               CASE WHEN total > 0 THEN ROUND(dormant_90d::numeric / total * 100, 1) ELSE NULL END AS pct
        FROM counts
    """)).first()
    if not row or row.pct is None or int(row.total or 0) < 100:
        return []
    pct = float(row.pct)
    if pct < 30:
        return []
    sev = "warn" if pct < 50 else "critical"
    return [{
        "title": f"{pct}% of marketing audience dormant for 90+ days",
        "severity": sev,
        "evidence": f"{int(row.dormant_90d or 0):,} of {int(row.total or 0):,} profiles (audience-wide, includes non-owners) haven't fired any event in 90+ days.",
        "action": "Run a re-activation sequence on the dormant audience; sunset profiles that don't engage within 30d to protect email deliverability and reduce Klaviyo cost. Owners need a separate retention track — they shouldn't get sunset just because they don't open marketing emails.",
        "impact": "Active list of 12k beats dormant list of 30k — better deliverability, lower Klaviyo bill, more meaningful campaign analytics. Don't sunset owners by accident.",
        "key": "mkt.dormant_share",
    }]


def _rec_firmware_release_stalled(db: Session) -> list[dict[str, Any]]:
    """A firmware release in 'beta' or 'alpha' state with no
    progress in 14 days is probably stuck and needs a ship/kill
    decision."""
    try:
        rows = db.execute(text("""
            SELECT
                release_id, version, status, updated_at,
                EXTRACT(EPOCH FROM (NOW() - updated_at))/86400 AS days_since_update
            FROM firmware_releases
            WHERE status IN ('alpha', 'beta')
              AND updated_at < NOW() - INTERVAL '14 days'
            ORDER BY updated_at ASC
            LIMIT 5
        """)).all()
    except Exception:
        return []
    if not rows:
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        days = int(r.days_since_update or 0)
        out.append({
            "title": f"Firmware {r.version} stalled in {r.status} for {days}d",
            "severity": "warn" if days < 30 else "critical",
            "evidence": f"Release {r.release_id} ({r.version}) hasn't moved since {r.updated_at.isoformat() if r.updated_at else 'unknown'}.",
            "action": "Open the Firmware Hub release detail; either promote it to gamma/production or kill it with an ECR. Stalled releases block the next test slot.",
            "impact": "Each week of stall pushes the next firmware delivery back by a sprint and dilutes the beta cohort signal-to-noise.",
            "key": f"fw.release_stalled.{r.release_id}",
        })
    return out


def _rec_anomaly_for(metric_key: str, division: str, severity_floor: str = "moderate") -> Callable[[Session], list[dict[str, Any]]]:
    """Build a generator that surfaces a recommendation when the named
    metric's current 7-day average is statistically off from its
    rolling 28-day baseline (z-score severity ≥ ``severity_floor``).

    Closure pattern lets the same anomaly logic spawn one rec per
    metric without N copy-paste functions. Each registered metric
    gets a stable key so dedup works.
    """
    severity_rank = {"normal": 0, "mild": 1, "moderate": 2, "critical": 3}
    floor = severity_rank.get(severity_floor, 2)

    def generator(db: Session) -> list[dict[str, Any]]:
        try:
            from app.services.trend_analysis import (
                detect_anomaly, kpi_daily_series, telemetry_history_daily_series, two_window_split,
            )
            from app.api.routes.trends import METRICS
        except Exception:
            return []
        spec = METRICS.get(metric_key)
        if not spec:
            return []
        try:
            if spec["table"] == "kpi":
                series = kpi_daily_series(db, spec["col"], days=35)
            else:
                series = telemetry_history_daily_series(db, spec["col"], days=35)
        except Exception:
            return []
        if len(series) < 14:
            return []
        cur_7d, _ = two_window_split(series, current_window_days=7)
        anomaly = detect_anomaly(cur_7d, series[:-7])
        if severity_rank.get(anomaly.severity, 0) < floor:
            return []
        # Decide whether the anomaly is bad or good given the metric's
        # up-is-good orientation. If telemetry_errors spiked above
        # baseline, that's bad; if revenue dipped below baseline, also
        # bad. Skip "good" anomalies — the recommendations engine is
        # for actions, and a positive surprise doesn't need one.
        bad_direction = (
            (anomaly.direction == "above" and not spec["up_is_good"])
            or (anomaly.direction == "below" and spec["up_is_good"])
        )
        if not bad_direction:
            return []
        sev_label = "warn" if anomaly.severity == "moderate" else "critical"
        verb = "above" if anomaly.direction == "above" else "below"
        return [{
            "title": f"{spec['label']} is {anomaly.severity} ({verb} 28d baseline) — z={anomaly.z_score:+.1f}",
            "severity": sev_label,
            "evidence": (
                f"7-day avg: {anomaly.current:.2f}. 28-day baseline mean: {anomaly.baseline_mean:.2f} "
                f"(std {anomaly.baseline_std:.2f}, n={anomaly.n_observations})."
            ),
            "action": (
                f"Open the {division.upper()} page and click into {spec['label']}'s underlying chart. "
                f"Look for the breakpoint date and cross-reference with firmware releases, campaigns, "
                f"or vendor changes in the LORE EVENTS feed."
            ),
            "impact": (
                f"Anomaly detection catches regressions ~3-7 days earlier than "
                f"single-threshold alerts. Recover this week, save the lagging "
                f"indicators (CSAT, support volume) from following."
            ),
            "key": f"{division}.anomaly.{metric_key}",
        }]
    generator.__name__ = f"_rec_anomaly_{metric_key}"
    return generator


# Anomaly generators — one per metric, registered into the right
# division below.
_anomaly_pe_cook_success = _rec_anomaly_for("cook_success_rate", "pe")
_anomaly_pe_telemetry_errors = _rec_anomaly_for("telemetry_errors", "pe")
_anomaly_pe_telemetry_sessions = _rec_anomaly_for("telemetry_sessions", "pe")
_anomaly_cx_tickets = _rec_anomaly_for("tickets_created", "cx")
_anomaly_cx_csat = _rec_anomaly_for("csat", "cx")
_anomaly_cx_first_response = _rec_anomaly_for("first_response_time", "cx")
_anomaly_marketing_revenue = _rec_anomaly_for("revenue", "marketing")
_anomaly_marketing_orders = _rec_anomaly_for("orders", "marketing")


def _rec_pe_engineering_stale(db: Session) -> list[dict[str, Any]]:
    """Flag products that haven't seen any engineering-folder file
    activity in 30+ days. Helps spot stalled product workstreams
    before they show up as a missed deadline."""
    try:
        rows = db.execute(text("""
            SELECT
                spider_product,
                MAX(modified_at_remote) AS last_modified,
                EXTRACT(EPOCH FROM (NOW() - MAX(modified_at_remote)))/86400 AS days_stale
            FROM sharepoint_documents
            WHERE dashboard_division = 'pe'
              AND is_folder = false
              AND spider_product IS NOT NULL
            GROUP BY spider_product
            HAVING MAX(modified_at_remote) < NOW() - INTERVAL '30 days'
            ORDER BY days_stale DESC
            LIMIT 5
        """)).all()
    except Exception:
        return []
    out = []
    for r in rows:
        days = int(r.days_stale or 0)
        out.append({
            "title": f"{r.spider_product} engineering activity stalled — {days}d since last file change",
            "severity": "info" if days < 60 else "warn",
            "evidence": f"Last Engineering folder change: {r.last_modified.isoformat() if r.last_modified else 'unknown'}.",
            "action": f"Open the {r.spider_product} card in SharePoint and check whether the workstream is paused intentionally or genuinely stuck. If active, ping the engineering owner.",
            "impact": "Catches stalled product workstreams ~weeks before the missed-deadline signal hits.",
            "key": f"pe.engineering_stale.{r.spider_product}",
        })
    return out


def _rec_ops_recent_quotes(db: Session) -> list[dict[str, Any]]:
    """Surface fresh quotation/PO files in the Project Management
    folder so Operations can see vendor activity at a glance."""
    try:
        rows = db.execute(text("""
            SELECT spider_product, COUNT(*) AS n
            FROM sharepoint_documents
            WHERE dashboard_division = 'operations'
              AND is_folder = false
              AND modified_at_remote >= NOW() - INTERVAL '7 days'
              AND (LOWER(name) LIKE '%quot%' OR LOWER(name) LIKE '%po %' OR LOWER(name) LIKE '%purchase%' OR LOWER(name) LIKE '%price%')
            GROUP BY spider_product
            HAVING COUNT(*) >= 3
            ORDER BY 2 DESC
            LIMIT 3
        """)).all()
    except Exception:
        return []
    return [{
        "title": f"{r.n} new quote/PO files for {r.spider_product} this week",
        "severity": "info",
        "evidence": f"Detected in the Project Management folder (filenames matching 'quote', 'PO', 'purchase', 'price').",
        "action": f"Skim the latest quotations on the Operations page's SharePoint card. If a vendor decision is pending, pull it forward.",
        "impact": "Vendor decisions made within a week of quoting save 3-5d of Q&A churn vs reviewing later.",
        "key": f"ops.fresh_quotes.{r.spider_product}",
    } for r in rows]


def _rec_mfg_qc_documents(db: Session) -> list[dict[str, Any]]:
    """When new Production-and-QC documents land on Huntsman or
    Webcraft (the active SKUs), tell the manufacturing owner."""
    try:
        rows = db.execute(text("""
            SELECT spider_product, COUNT(*) AS n, MAX(modified_at_remote) AS last_mod
            FROM sharepoint_documents
            WHERE dashboard_division = 'manufacturing'
              AND is_folder = false
              AND modified_at_remote >= NOW() - INTERVAL '3 days'
              AND spider_product IN ('Huntsman', 'Webcraft', 'Giant Huntsman', 'Giant Webcraft')
            GROUP BY spider_product
            HAVING COUNT(*) >= 5
            ORDER BY 2 DESC
            LIMIT 4
        """)).all()
    except Exception:
        return []
    return [{
        "title": f"{r.n} Production/QC files updated for {r.spider_product} in last 3 days",
        "severity": "info",
        "evidence": f"Most recent: {r.last_mod.isoformat() if r.last_mod else 'unknown'}.",
        "action": "Check the SharePoint Production & QC card for new yield reports, defect logs, or inspection records. Push any defect-reason updates back to the Issue Radar.",
        "impact": "Fast loops between QC findings and engineering ECRs cut defect-rate-recovery time roughly in half.",
        "key": f"mfg.qc_activity.{r.spider_product}",
    } for r in rows]


_GENERATORS: dict[str, list[Callable[[Session], list[dict[str, Any]]]]] = {
    "pe": [
        _rec_pe_session_freshness,
        _rec_pe_app_install_rate,
        _rec_pe_cook_success,
        _rec_pe_disconnect_rate,
        _rec_pe_overshoot_rate,
        _rec_pe_engineering_stale,
        _anomaly_pe_cook_success,
        _anomaly_pe_telemetry_errors,
        _anomaly_pe_telemetry_sessions,
    ],
    "cx": [
        _rec_cx_first_response_breach,
        _rec_cx_huntsman_ticket_spike,
        _rec_cx_backlog_growing,
        _anomaly_cx_tickets,
        _anomaly_cx_csat,
        _anomaly_cx_first_response,
    ],
    "marketing": [
        _rec_marketing_friendbuy_attribution,
        _rec_marketing_unengaged_180d,
        _rec_marketing_unengaged_share,
        _anomaly_marketing_revenue,
        _anomaly_marketing_orders,
    ],
    "operations": [
        _rec_ops_order_aging,
        _rec_ops_recent_quotes,
    ],
    "firmware": [
        _rec_firmware_beta_cohort_size,
        _rec_firmware_release_stalled,
    ],
    "manufacturing": [
        _rec_mfg_qc_documents,
    ],
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
