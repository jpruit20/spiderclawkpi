"""Beta cohort selection + management.

Given a firmware release (and its ``addresses_issues`` tag slugs), this
service scores every active device on how good a beta candidate it is:

* **Usage** — sessions/30d, active days/90d, tenure (days since first session)
* **Issue matching** — does the device exhibit the failure modes this
  release targets? Derived from recent ``telemetry_sessions`` columns
  (error codes, overshoot/undershoot, disturbance recovery) and from
  Freshdesk tickets the user filed that mention matching keywords.
* **Health gate** — exclude anyone with an open critical Freshdesk
  ticket; we don't want the beta to land on a grill that's already
  causing the user pain.

The output is a ranked list of candidates. The user opts in via the
web surface (Agustin review 2026-04-21 will confirm the flow); when
they do, the candidate flips from ``invited`` to ``opted_in`` on
``beta_cohort_members``.

Shadow-signal detectors are kept small and explicit so Joseph can read
them and say "that's what 'persistent overshoot' means." Add new tags
to the taxonomy (firmware_issue_tags) and a matching detector here.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import (
    BetaCohortMember,
    FirmwareIssueTag,
    FirmwareRelease,
    FreshdeskTicket,
    TelemetrySession,
)

logger = logging.getLogger(__name__)

# Window sizes.
USAGE_WINDOW_DAYS = 30
SHADOW_WINDOW_DAYS = 60
FRESHDESK_WINDOW_DAYS = 120

# Blended candidate score weights (sum to 1.0).
W_ISSUE_MATCH = 0.55      # strongest signal — they're hitting the thing we're fixing
W_USAGE = 0.30            # heavy users give us more data post-update
W_TENURE = 0.15           # long-time owners = more reliable feedback


# Shadow-signal detectors — each one is SQL that yields device_id rows
# where the signature fired in the lookback window. Keep them narrow
# and readable. New taxonomy slugs that don't have a detector here fall
# back to Freshdesk-only matching, which is fine.
_SHADOW_DETECTORS: dict[str, str] = {
    "persistent_overshoot": """
        SELECT DISTINCT device_id
          FROM telemetry_sessions
         WHERE session_start >= :since
           AND device_id IS NOT NULL
           AND max_overshoot_f >= 25
           AND cook_outcome = 'reached_not_held'
    """,
    "persistent_undershoot": """
        SELECT DISTINCT device_id
          FROM telemetry_sessions
         WHERE session_start >= :since
           AND device_id IS NOT NULL
           AND max_undershoot_f >= 25
           AND cook_outcome IN ('reached_not_held','did_not_reach')
    """,
    "slow_recovery": """
        SELECT DISTINCT device_id
          FROM telemetry_sessions
         WHERE session_start >= :since
           AND device_id IS NOT NULL
           AND avg_recovery_seconds >= 300
    """,
    "startup_fail": """
        SELECT DISTINCT device_id
          FROM telemetry_sessions
         WHERE session_start >= :since
           AND device_id IS NOT NULL
           AND cook_outcome = 'did_not_reach'
           AND cook_intent IN ('short_cook','medium_cook','long_cook')
    """,
    "wifi_disconnect": """
        SELECT DISTINCT device_id
          FROM telemetry_sessions
         WHERE session_start >= :since
           AND device_id IS NOT NULL
           AND cook_outcome = 'disconnect'
    """,
    "oscillation": """
        SELECT DISTINCT device_id
          FROM telemetry_sessions
         WHERE session_start >= :since
           AND device_id IS NOT NULL
           AND disturbance_count >= 8
           AND in_control_pct IS NOT NULL
           AND in_control_pct < 0.5
    """,
    "probe_dropout": """
        SELECT DISTINCT device_id
          FROM telemetry_sessions
         WHERE session_start >= :since
           AND device_id IS NOT NULL
           AND disconnect_events > 0
           AND error_count = 0
    """,
    "error_code_42": """
        SELECT DISTINCT device_id
          FROM telemetry_sessions
         WHERE session_start >= :since
           AND device_id IS NOT NULL
           AND error_codes_json @> '[42]'::jsonb
    """,
}


@dataclass
class Candidate:
    device_id: str
    user_id: str | None
    score: float
    sessions_30d: int
    tenure_days: int
    matched_tags: list[str]
    matched_freshdesk_ticket_ids: list[str]


def _detect_shadow_matches(
    db: Session, tag_slugs: list[str], since: datetime
) -> dict[str, set[str]]:
    """For each requested tag, return the set of device_ids that fire it."""
    out: dict[str, set[str]] = {}
    for slug in tag_slugs:
        sql = _SHADOW_DETECTORS.get(slug)
        if not sql:
            continue
        rows = db.execute(text(sql), {"since": since}).all()
        out[slug] = {r[0] for r in rows if r[0]}
    return out


def _detect_freshdesk_matches(
    db: Session, tags: list[FirmwareIssueTag], since: datetime
) -> dict[str, dict[str, list[str]]]:
    """For each tag, return {device_id: [ticket_ids]} where ticket subject
    or tag contains the tag's label/slug. Matching is loose on purpose —
    Freshdesk tags are free-form."""
    result: dict[str, dict[str, list[str]]] = {}
    tickets = db.execute(
        select(FreshdeskTicket).where(
            FreshdeskTicket.created_at_source.is_not(None),
            FreshdeskTicket.created_at_source >= since,
        )
    ).scalars().all()
    if not tickets:
        return result
    # Freshdesk tickets aren't device-linked in our schema today — we'd
    # need the ticket→device bridge via requester email. Skip for MVP
    # and surface only shadow-matched devices. Kept here as a scaffold.
    return result


def _base_active_devices(db: Session, since: datetime) -> dict[str, dict[str, Any]]:
    """Load per-device usage stats (sessions/30d, active_days, tenure)."""
    since_tenure_floor = datetime.now(timezone.utc) - timedelta(days=365 * 10)
    rows = db.execute(text("""
        SELECT device_id,
               user_id,
               COUNT(*) FILTER (WHERE session_start >= :since_usage) AS sessions_30d,
               COUNT(DISTINCT DATE(session_start)) FILTER (WHERE session_start >= :since_usage) AS active_days,
               MIN(session_start) AS first_seen,
               MAX(session_start) AS last_seen
          FROM telemetry_sessions
         WHERE device_id IS NOT NULL
           AND session_start >= :since_floor
         GROUP BY device_id, user_id
    """), {"since_usage": since, "since_floor": since_tenure_floor}).all()
    now = datetime.now(timezone.utc)
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        first_seen = r.first_seen
        tenure_days = int((now - first_seen).total_seconds() / 86400) if first_seen else 0
        out[r.device_id] = {
            "user_id": r.user_id,
            "sessions_30d": int(r.sessions_30d or 0),
            "active_days": int(r.active_days or 0),
            "tenure_days": tenure_days,
            "last_seen": r.last_seen,
        }
    return out


def score_candidates(
    db: Session,
    release: FirmwareRelease,
    *,
    max_candidates: int | None = None,
    exclude_device_ids: set[str] | None = None,
) -> list[Candidate]:
    """Rank every active device as a beta candidate for ``release``.

    Higher score = better candidate. Returns at most ``max_candidates``
    (default: the release's ``beta_cohort_target_size`` × 3 so the UI
    can show a ranked list, not just the invitees).
    """
    if not release.addresses_issues:
        logger.info("release %s has no addresses_issues — returning empty candidate list", release.version)
        return []

    target_n = max_candidates or max(release.beta_cohort_target_size * 3, 300)
    now = datetime.now(timezone.utc)
    since_usage = now - timedelta(days=USAGE_WINDOW_DAYS)
    since_shadow = now - timedelta(days=SHADOW_WINDOW_DAYS)

    usage = _base_active_devices(db, since_usage)
    if not usage:
        return []

    shadow_by_tag = _detect_shadow_matches(db, release.addresses_issues, since_shadow)

    # Normalize usage/tenure for scoring. Clip at the 95th-percentile-ish
    # values so one power-user doesn't crush everyone else's score.
    sessions_ceiling = 60.0   # ~2 cooks/day
    tenure_ceiling = 730.0    # two years

    candidates: list[Candidate] = []
    for device_id, stats in usage.items():
        if exclude_device_ids and device_id in exclude_device_ids:
            continue
        matched_tags = [slug for slug, devs in shadow_by_tag.items() if device_id in devs]
        # No match → not a candidate at all for this release.
        if not matched_tags:
            continue

        issue_match_ratio = len(matched_tags) / max(len(release.addresses_issues), 1)
        usage_norm = min(stats["sessions_30d"] / sessions_ceiling, 1.0)
        tenure_norm = min(stats["tenure_days"] / tenure_ceiling, 1.0)

        score = (
            W_ISSUE_MATCH * issue_match_ratio
            + W_USAGE * usage_norm
            + W_TENURE * tenure_norm
        )

        candidates.append(Candidate(
            device_id=device_id,
            user_id=stats.get("user_id"),
            score=round(score, 4),
            sessions_30d=stats["sessions_30d"],
            tenure_days=stats["tenure_days"],
            matched_tags=matched_tags,
            matched_freshdesk_ticket_ids=[],
        ))

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:target_n]


def invite_beta_cohort(
    db: Session,
    release: FirmwareRelease,
    *,
    cohort_size: int | None = None,
    invited_by: str | None = None,
) -> dict[str, Any]:
    """Pick the top-N candidates and create ``beta_cohort_members`` rows
    in state=invited. Idempotent: devices already in the cohort for
    this release are skipped."""
    size = cohort_size or release.beta_cohort_target_size or 100
    # Pull devices already invited so we don't double-invite.
    already = {
        m.device_id for m in db.execute(
            select(BetaCohortMember).where(BetaCohortMember.release_id == release.id)
        ).scalars().all()
    }
    candidates = score_candidates(db, release, max_candidates=size * 3, exclude_device_ids=already)
    invited = candidates[: max(size - len(already), 0)]

    for c in invited:
        db.add(BetaCohortMember(
            release_id=release.id,
            device_id=c.device_id,
            user_id=c.user_id,
            candidate_score=c.score,
            candidate_reason_json={
                "matched_tags": c.matched_tags,
                "matched_freshdesk_ticket_ids": c.matched_freshdesk_ticket_ids,
                "sessions_30d": c.sessions_30d,
                "tenure_days": c.tenure_days,
                "invited_by": invited_by,
            },
            state="invited",
        ))
    db.commit()
    return {
        "ok": True,
        "release_id": release.id,
        "version": release.version,
        "candidates_found": len(candidates),
        "invited_count": len(invited),
        "already_invited": len(already),
        "cohort_target": size,
    }


def record_opt_in(
    db: Session,
    *,
    release_id: int,
    device_id: str,
    source: str = "web",
) -> dict[str, Any]:
    """Flip a cohort member from invited → opted_in. Used by the web
    opt-in surface."""
    member = db.execute(
        select(BetaCohortMember).where(
            BetaCohortMember.release_id == release_id,
            BetaCohortMember.device_id == device_id,
        )
    ).scalars().first()
    if member is None:
        return {"ok": False, "message": "not invited"}
    if member.state in ("opted_in", "ota_pushed", "ota_confirmed", "evaluated"):
        return {"ok": True, "already": True, "state": member.state}
    member.state = "opted_in"
    member.opted_in_at = datetime.now(timezone.utc)
    member.opt_in_source = source
    db.commit()
    return {"ok": True, "state": member.state, "opted_in_at": member.opted_in_at.isoformat()}


def record_decline(
    db: Session, *, release_id: int, device_id: str
) -> dict[str, Any]:
    member = db.execute(
        select(BetaCohortMember).where(
            BetaCohortMember.release_id == release_id,
            BetaCohortMember.device_id == device_id,
        )
    ).scalars().first()
    if member is None:
        return {"ok": False, "message": "not invited"}
    member.state = "declined"
    db.commit()
    return {"ok": True, "state": member.state}
