"""Post-deploy verdict pass for the Firmware Beta program.

For every cohort member past the observation window, compare how often
the release's addressed failure modes fired before vs after the user
opted in (or after OTA push if we tracked that). Classify each device
as resolved / partial / still_failing / inconclusive / pending and
store the evidence on ``beta_cohort_members.verdict_json``. Roll the
per-device verdicts up into ``firmware_releases.beta_report_json``.

The shadow-signal SQL here mirrors the detectors in ``beta_cohort.py``.
Both files point at the same predicates — the cohort module returns
distinct device_ids that have fired the signature at all; the verdict
module returns per-device session counts so we can measure deltas.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import BetaCohortMember, FirmwareRelease


logger = logging.getLogger(__name__)

VERDICT_WINDOW_DAYS = 14
MIN_PRE_FIRINGS_FOR_JUDGMENT = 3
RESOLVED_REDUCTION = 0.80
PARTIAL_REDUCTION = 0.50

RELEASE_RESOLVED_RATIO = 0.70
RELEASE_REGRESSION_RATIO = 0.30


# Per-signal count queries. Each returns (device_id, n) for devices in
# :device_ids across [:start, :end). Mirrors the WHERE clauses in
# beta_cohort._SHADOW_DETECTORS — keep them in sync.
_SIGNAL_COUNT_QUERIES: dict[str, str] = {
    "persistent_overshoot": """
        SELECT device_id, COUNT(*) AS n
          FROM telemetry_sessions
         WHERE device_id = ANY(:device_ids)
           AND session_start >= :start AND session_start < :end
           AND max_overshoot_f >= 25
           AND cook_outcome = 'reached_not_held'
         GROUP BY device_id
    """,
    "persistent_undershoot": """
        SELECT device_id, COUNT(*) AS n
          FROM telemetry_sessions
         WHERE device_id = ANY(:device_ids)
           AND session_start >= :start AND session_start < :end
           AND max_undershoot_f >= 25
           AND cook_outcome IN ('reached_not_held','did_not_reach')
         GROUP BY device_id
    """,
    "slow_recovery": """
        SELECT device_id, COUNT(*) AS n
          FROM telemetry_sessions
         WHERE device_id = ANY(:device_ids)
           AND session_start >= :start AND session_start < :end
           AND avg_recovery_seconds >= 300
         GROUP BY device_id
    """,
    "startup_fail": """
        SELECT device_id, COUNT(*) AS n
          FROM telemetry_sessions
         WHERE device_id = ANY(:device_ids)
           AND session_start >= :start AND session_start < :end
           AND cook_outcome = 'did_not_reach'
           AND cook_intent IN ('short_cook','medium_cook','long_cook')
         GROUP BY device_id
    """,
    "wifi_disconnect": """
        SELECT device_id, COUNT(*) AS n
          FROM telemetry_sessions
         WHERE device_id = ANY(:device_ids)
           AND session_start >= :start AND session_start < :end
           AND cook_outcome = 'disconnect'
         GROUP BY device_id
    """,
    "oscillation": """
        SELECT device_id, COUNT(*) AS n
          FROM telemetry_sessions
         WHERE device_id = ANY(:device_ids)
           AND session_start >= :start AND session_start < :end
           AND disturbance_count >= 8
           AND in_control_pct IS NOT NULL
           AND in_control_pct < 0.5
         GROUP BY device_id
    """,
    "probe_dropout": """
        SELECT device_id, COUNT(*) AS n
          FROM telemetry_sessions
         WHERE device_id = ANY(:device_ids)
           AND session_start >= :start AND session_start < :end
           AND disconnect_events > 0
           AND error_count = 0
         GROUP BY device_id
    """,
    "error_code_42": """
        SELECT device_id, COUNT(*) AS n
          FROM telemetry_sessions
         WHERE device_id = ANY(:device_ids)
           AND session_start >= :start AND session_start < :end
           AND error_codes_json @> '[42]'::jsonb
         GROUP BY device_id
    """,
}


def _session_totals(
    db: Session, device_ids: list[str], start: datetime, end: datetime
) -> dict[str, int]:
    """How many sessions each device ran in [start, end). Used to
    distinguish `no post activity` from `post activity but issue fixed`."""
    if not device_ids:
        return {}
    rows = db.execute(text("""
        SELECT device_id, COUNT(*) AS n
          FROM telemetry_sessions
         WHERE device_id = ANY(:device_ids)
           AND session_start >= :start AND session_start < :end
         GROUP BY device_id
    """), {"device_ids": device_ids, "start": start, "end": end}).all()
    return {r[0]: int(r[1]) for r in rows}


def _tag_firings(
    db: Session,
    tag_slug: str,
    device_ids: list[str],
    start: datetime,
    end: datetime,
) -> dict[str, int]:
    sql = _SIGNAL_COUNT_QUERIES.get(tag_slug)
    if not sql or not device_ids:
        return {}
    rows = db.execute(text(sql), {"device_ids": device_ids, "start": start, "end": end}).all()
    return {r[0]: int(r[1]) for r in rows}


def _classify_device(
    *,
    addressed_tags: list[str],
    pre_firings: dict[str, int],
    post_firings: dict[str, int],
    pre_sessions: int,
    post_sessions: int,
) -> tuple[str, dict[str, Any]]:
    """Return (verdict, evidence) for a single device.

    Verdict ∈ {resolved, partial, still_failing, inconclusive, no_post_data}.
    """
    per_tag: list[dict[str, Any]] = []
    judgable_tags: list[dict[str, Any]] = []
    for slug in addressed_tags:
        pre = pre_firings.get(slug, 0)
        post = post_firings.get(slug, 0)
        entry: dict[str, Any] = {"slug": slug, "pre": pre, "post": post}
        if pre >= MIN_PRE_FIRINGS_FOR_JUDGMENT:
            reduction = (pre - post) / pre
            entry["reduction"] = round(reduction, 3)
            if reduction >= RESOLVED_REDUCTION:
                entry["verdict"] = "resolved"
            elif reduction >= PARTIAL_REDUCTION:
                entry["verdict"] = "partial"
            else:
                entry["verdict"] = "still_failing"
            judgable_tags.append(entry)
        else:
            entry["verdict"] = "inconclusive"
        per_tag.append(entry)

    evidence: dict[str, Any] = {
        "per_tag": per_tag,
        "pre_sessions": pre_sessions,
        "post_sessions": post_sessions,
        "judgable_tag_count": len(judgable_tags),
    }

    if post_sessions == 0:
        return "no_post_data", evidence

    if not judgable_tags:
        return "inconclusive", evidence

    # Majority rules across tags with a strong enough baseline.
    resolved_count = sum(1 for e in judgable_tags if e["verdict"] == "resolved")
    partial_count = sum(1 for e in judgable_tags if e["verdict"] == "partial")
    fail_count = sum(1 for e in judgable_tags if e["verdict"] == "still_failing")
    n = len(judgable_tags)

    if resolved_count == n:
        device_verdict = "resolved"
    elif (resolved_count + partial_count) / n >= 0.5 and fail_count == 0:
        device_verdict = "resolved" if resolved_count >= partial_count else "partial"
    elif fail_count / n > 0.5:
        device_verdict = "still_failing"
    else:
        device_verdict = "partial"

    return device_verdict, evidence


def evaluate_release(
    db: Session,
    release: FirmwareRelease,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Run the verdict pass for one release. Writes per-device verdicts
    onto ``beta_cohort_members.verdict_json`` and a rollup onto
    ``firmware_releases.beta_report_json``.

    ``force`` re-evaluates members already in state=evaluated.
    """
    now = now or datetime.now(timezone.utc)
    addressed = release.addresses_issues or []
    if not addressed:
        return {"ok": False, "message": "release has no addresses_issues"}

    members = db.execute(
        select(BetaCohortMember).where(
            BetaCohortMember.release_id == release.id,
            BetaCohortMember.state.in_(("opted_in", "ota_pushed", "ota_confirmed", "evaluated")),
        )
    ).scalars().all()
    if not members:
        return {"ok": True, "evaluated": 0, "message": "no opted-in members"}

    window = timedelta(days=VERDICT_WINDOW_DAYS)
    # Partition members by "ready to evaluate" vs "still in observation window".
    ready: list[tuple[BetaCohortMember, datetime]] = []
    pending_count = 0
    for m in members:
        # Anchor = first moment firmware could have applied. OTA push is
        # the ground truth once wired; until then we use opted_in_at as
        # the proxy. Skip members with no anchor.
        t0 = m.ota_pushed_at or m.opted_in_at
        if t0 is None:
            pending_count += 1
            continue
        if now - t0 < window:
            pending_count += 1
            continue
        if m.state == "evaluated" and not force:
            # Already scored in a previous pass — leave as-is.
            ready.append((m, t0))
            continue
        ready.append((m, t0))

    # Compute pre/post firings in bulk per tag. Each member has its own
    # t0, so "bulk" here means: gather all unique t0 values, partition
    # members by t0, and run one query per (tag, t0). For typical cohort
    # sizes (≤100 members) this is a handful of queries per pass.
    by_t0: dict[datetime, list[BetaCohortMember]] = {}
    for m, t0 in ready:
        by_t0.setdefault(t0, []).append(m)

    # Collect device-level results by member id.
    results: dict[int, tuple[str, dict[str, Any]]] = {}
    for t0, ms in by_t0.items():
        device_ids = [m.device_id for m in ms]
        pre_start = t0 - window
        post_end = t0 + window

        pre_firings_by_tag = {
            slug: _tag_firings(db, slug, device_ids, pre_start, t0) for slug in addressed
        }
        post_firings_by_tag = {
            slug: _tag_firings(db, slug, device_ids, t0, post_end) for slug in addressed
        }
        pre_sessions = _session_totals(db, device_ids, pre_start, t0)
        post_sessions = _session_totals(db, device_ids, t0, post_end)

        for m in ms:
            pre = {slug: pre_firings_by_tag[slug].get(m.device_id, 0) for slug in addressed}
            post = {slug: post_firings_by_tag[slug].get(m.device_id, 0) for slug in addressed}
            verdict, evidence = _classify_device(
                addressed_tags=addressed,
                pre_firings=pre,
                post_firings=post,
                pre_sessions=pre_sessions.get(m.device_id, 0),
                post_sessions=post_sessions.get(m.device_id, 0),
            )
            evidence["t0"] = t0.isoformat()
            evidence["verdict"] = verdict
            evidence["evaluated_at"] = now.isoformat()
            results[m.id] = (verdict, evidence)

    # Persist per-member verdicts.
    tally: dict[str, int] = {"pending": pending_count}
    for m, _ in ready:
        verdict, evidence = results[m.id]
        m.verdict_json = evidence
        m.evaluated_at = now
        m.state = "evaluated"
        tally[verdict] = tally.get(verdict, 0) + 1

    # Release-level health.
    judgable = sum(tally.get(v, 0) for v in ("resolved", "partial", "still_failing"))
    release_health = "insufficient_data"
    if judgable >= 5:
        good_ratio = (tally.get("resolved", 0) + tally.get("partial", 0)) / judgable
        if good_ratio >= RELEASE_RESOLVED_RATIO:
            release_health = "resolved"
        elif good_ratio >= RELEASE_REGRESSION_RATIO:
            release_health = "mixed"
        else:
            release_health = "regression"

    report = {
        "evaluated_at": now.isoformat(),
        "addresses_issues": addressed,
        "window_days": VERDICT_WINDOW_DAYS,
        "tally": tally,
        "judgable_devices": judgable,
        "release_health": release_health,
    }
    release.beta_report_json = report
    db.commit()
    logger.info(
        "beta verdict pass release=%s tally=%s health=%s",
        release.version, tally, release_health,
    )
    return {"ok": True, "release_id": release.id, "version": release.version, **report}


def run_beta_verdict_pass(db: Session) -> dict[str, Any]:
    """Daily scheduler entrypoint. Evaluates every non-draft release
    that has opted-in members. Safe to run repeatedly — existing
    evaluated rows are re-scored (cheap) so the rollup stays live."""
    releases = db.execute(
        select(FirmwareRelease).where(
            FirmwareRelease.status.in_(("beta", "beta_evaluating", "approved", "gamma", "ga"))
        )
    ).scalars().all()
    out: list[dict[str, Any]] = []
    for r in releases:
        try:
            out.append(evaluate_release(db, r, force=True))
        except Exception:
            logger.exception("beta verdict pass failed for release %s", r.version)
            db.rollback()
    return {"ok": True, "releases_evaluated": len(out), "results": out}
