"""Firmware Beta + Gamma Waves program API.

Phase 1 endpoints — everything needed for the dashboard to manage the
issue taxonomy, draft firmware releases, surface candidate devices,
and record opt-ins. The OTA push + Gamma scheduler pieces land in a
follow-up once the Agustin app-control review (2026-04-21) clarifies
the integration seam.

Public POST /api/beta/releases/{id}/opt-in is intentionally unauthed
(device+token combo instead); everything else is gated by the normal
dashboard session.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_dashboard_session
from app.models import (
    BetaCohortMember,
    FirmwareIssueTag,
    FirmwareRelease,
)
from app.services.beta_cohort import (
    invite_beta_cohort,
    record_decline,
    record_opt_in,
    score_candidates,
)
from app.services.beta_verdict import evaluate_release, run_beta_verdict_pass


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/beta",
    tags=["beta-program"],
    dependencies=[Depends(require_dashboard_session)],
)

# A separate router for the opt-in endpoint — deliberately NOT gated
# by the dashboard session so users can hit it from their browser.
# Auth happens at the application level via a per-invite token (TODO
# phase 2 once Agustin review confirms the web surface shape).
public_router = APIRouter(prefix="/api/beta/public", tags=["beta-program-public"])


SLUG_RE = re.compile(r"^[a-z0-9_]+$")


# ── Taxonomy CRUD ────────────────────────────────────────────────────


class IssueTagIn(BaseModel):
    slug: str = Field(..., min_length=2, max_length=64)
    label: str = Field(..., min_length=1, max_length=128)
    description: Optional[str] = None


class IssueTagPatch(BaseModel):
    label: Optional[str] = None
    description: Optional[str] = None
    archived: Optional[bool] = None


def _tag_row(tag: FirmwareIssueTag) -> dict[str, Any]:
    return {
        "id": tag.id,
        "slug": tag.slug,
        "label": tag.label,
        "description": tag.description,
        "archived": tag.archived,
        "created_by": tag.created_by,
        "created_at": tag.created_at.isoformat() if tag.created_at else None,
    }


@router.get("/tags")
def list_tags(include_archived: bool = False, db: Session = Depends(db_session)) -> dict[str, Any]:
    stmt = select(FirmwareIssueTag).order_by(FirmwareIssueTag.label)
    if not include_archived:
        stmt = stmt.where(FirmwareIssueTag.archived.is_(False))
    rows = db.execute(stmt).scalars().all()

    # Usage counts — how many releases reference each tag slug, and the
    # most recent release version that mentions it. Turns the taxonomy
    # tab from an admin form into a "which tags are actually in use"
    # decision panel.
    release_rows = db.execute(
        select(FirmwareRelease.version, FirmwareRelease.addresses_issues, FirmwareRelease.created_at)
        .order_by(desc(FirmwareRelease.created_at))
    ).all()
    usage_count: dict[str, int] = {}
    latest_by_slug: dict[str, str] = {}
    for version, issues, _created in release_rows:
        for slug in issues or []:
            usage_count[slug] = usage_count.get(slug, 0) + 1
            if slug not in latest_by_slug and version:
                latest_by_slug[slug] = version

    return {
        "tags": [
            {
                **_tag_row(t),
                "release_count": usage_count.get(t.slug, 0),
                "latest_release_version": latest_by_slug.get(t.slug),
            }
            for t in rows
        ]
    }


@router.post("/tags")
def create_tag(payload: IssueTagIn, db: Session = Depends(db_session)) -> dict[str, Any]:
    if not SLUG_RE.match(payload.slug):
        raise HTTPException(status_code=400, detail="slug must be lowercase letters, numbers, underscores")
    existing = db.execute(
        select(FirmwareIssueTag).where(FirmwareIssueTag.slug == payload.slug)
    ).scalars().first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="slug already exists")
    tag = FirmwareIssueTag(
        slug=payload.slug,
        label=payload.label,
        description=payload.description,
        created_by="dashboard",
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return _tag_row(tag)


@router.patch("/tags/{tag_id}")
def update_tag(tag_id: int, payload: IssueTagPatch, db: Session = Depends(db_session)) -> dict[str, Any]:
    tag = db.get(FirmwareIssueTag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="tag not found")
    if payload.label is not None:
        tag.label = payload.label
    if payload.description is not None:
        tag.description = payload.description
    if payload.archived is not None:
        tag.archived = payload.archived
    db.commit()
    db.refresh(tag)
    return _tag_row(tag)


# ── Releases ─────────────────────────────────────────────────────────


class FirmwareReleaseIn(BaseModel):
    version: str = Field(..., max_length=64)
    title: Optional[str] = Field(None, max_length=256)
    notes: Optional[str] = None
    addresses_issues: list[str] = Field(default_factory=list)
    beta_cohort_target_size: int = Field(100, ge=1, le=1000)
    clickup_task_id: Optional[str] = None
    git_commit_sha: Optional[str] = None


class FirmwareReleasePatch(BaseModel):
    title: Optional[str] = None
    notes: Optional[str] = None
    addresses_issues: Optional[list[str]] = None
    status: Optional[str] = None
    beta_cohort_target_size: Optional[int] = Field(None, ge=1, le=1000)
    clickup_task_id: Optional[str] = None
    git_commit_sha: Optional[str] = None


def _release_row(r: FirmwareRelease, db: Session | None = None) -> dict[str, Any]:
    cohort_counts: dict[str, int] = {}
    if db is not None:
        rows = db.execute(
            select(BetaCohortMember.state, func.count(BetaCohortMember.id))
            .where(BetaCohortMember.release_id == r.id)
            .group_by(BetaCohortMember.state)
        ).all()
        cohort_counts = {state: int(n) for (state, n) in rows}
    return {
        "id": r.id,
        "version": r.version,
        "title": r.title,
        "notes": r.notes,
        "addresses_issues": r.addresses_issues or [],
        "status": r.status,
        "beta_cohort_target_size": r.beta_cohort_target_size,
        "clickup_task_id": r.clickup_task_id,
        "git_commit_sha": r.git_commit_sha,
        "beta_iot_job_id": r.beta_iot_job_id,
        "gamma_plan": r.gamma_plan_json or {},
        "beta_report": r.beta_report_json or {},
        "created_by": r.created_by,
        "approved_by": r.approved_by,
        "approved_at": r.approved_at.isoformat() if r.approved_at else None,
        "released_at": r.released_at.isoformat() if r.released_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "cohort_counts": cohort_counts,
        "binary_url": getattr(r, "binary_url", None),
        "binary_sha256": getattr(r, "binary_sha256", None),
        "binary_size_bytes": getattr(r, "binary_size_bytes", None),
        "target_controller_model": getattr(r, "target_controller_model", None),
        "approved_for_alpha": bool(getattr(r, "approved_for_alpha", False)),
        "approved_for_beta": bool(getattr(r, "approved_for_beta", False)),
        "approved_for_gamma": bool(getattr(r, "approved_for_gamma", False)),
    }


def _validate_addresses_issues(db: Session, slugs: list[str]) -> None:
    if not slugs:
        return
    known = {
        t.slug for t in db.execute(
            select(FirmwareIssueTag).where(FirmwareIssueTag.slug.in_(slugs))
        ).scalars().all()
    }
    unknown = [s for s in slugs if s not in known]
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown issue tag slugs: {unknown}")


@router.get("/releases")
def list_releases(db: Session = Depends(db_session)) -> dict[str, Any]:
    rows = db.execute(select(FirmwareRelease).order_by(desc(FirmwareRelease.created_at))).scalars().all()
    return {"releases": [_release_row(r, db) for r in rows]}


@router.get("/summary")
def program_summary(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Compact roll-up for Executive/Overview cards. Returns counts of
    active releases, cohort fill, and recent verdict tallies."""
    releases = db.execute(
        select(FirmwareRelease).order_by(desc(FirmwareRelease.created_at))
    ).scalars().all()
    active = [r for r in releases if r.status not in ("draft", "ga", "rolled_back")]
    cohort_totals = dict(
        db.execute(
            select(BetaCohortMember.state, func.count(BetaCohortMember.id))
            .group_by(BetaCohortMember.state)
        ).all()
    )
    cohort_totals = {k: int(v) for k, v in cohort_totals.items()}

    recent_releases: list[dict[str, Any]] = []
    for r in releases[:5]:
        report = r.beta_report_json or {}
        recent_releases.append({
            "id": r.id,
            "version": r.version,
            "status": r.status,
            "addresses_issues": r.addresses_issues or [],
            "release_health": report.get("release_health"),
            "tally": report.get("tally", {}),
            "judgable_devices": report.get("judgable_devices", 0),
            "evaluated_at": report.get("evaluated_at"),
        })
    return {
        "total_releases": len(releases),
        "active_releases": len(active),
        "cohort_states": cohort_totals,
        "recent": recent_releases,
    }


@router.post("/releases")
def create_release(payload: FirmwareReleaseIn, db: Session = Depends(db_session)) -> dict[str, Any]:
    _validate_addresses_issues(db, payload.addresses_issues)
    existing = db.execute(
        select(FirmwareRelease).where(FirmwareRelease.version == payload.version)
    ).scalars().first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="version already exists")
    r = FirmwareRelease(
        version=payload.version,
        title=payload.title,
        notes=payload.notes,
        addresses_issues=payload.addresses_issues,
        beta_cohort_target_size=payload.beta_cohort_target_size,
        clickup_task_id=payload.clickup_task_id,
        git_commit_sha=payload.git_commit_sha,
        status="draft",
        created_by="dashboard",
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return _release_row(r, db)


@router.patch("/releases/{release_id}")
def update_release(release_id: int, payload: FirmwareReleasePatch, db: Session = Depends(db_session)) -> dict[str, Any]:
    r = db.get(FirmwareRelease, release_id)
    if r is None:
        raise HTTPException(status_code=404, detail="release not found")
    if payload.addresses_issues is not None:
        _validate_addresses_issues(db, payload.addresses_issues)
        r.addresses_issues = payload.addresses_issues
    if payload.title is not None:
        r.title = payload.title
    if payload.notes is not None:
        r.notes = payload.notes
    if payload.status is not None:
        r.status = payload.status
    if payload.beta_cohort_target_size is not None:
        r.beta_cohort_target_size = payload.beta_cohort_target_size
    if payload.clickup_task_id is not None:
        r.clickup_task_id = payload.clickup_task_id
    if payload.git_commit_sha is not None:
        r.git_commit_sha = payload.git_commit_sha
    db.commit()
    db.refresh(r)
    return _release_row(r, db)


# ── Candidate selection + cohort ─────────────────────────────────────


@router.get("/releases/{release_id}/candidates")
def get_candidates(release_id: int, limit: int = 200, db: Session = Depends(db_session)) -> dict[str, Any]:
    r = db.get(FirmwareRelease, release_id)
    if r is None:
        raise HTTPException(status_code=404, detail="release not found")
    ranked = score_candidates(db, r, max_candidates=max(limit, 1))
    return {
        "release_id": r.id,
        "version": r.version,
        "addresses_issues": r.addresses_issues or [],
        "candidates": [
            {
                "device_id": c.device_id,
                "user_id": c.user_id,
                "score": c.score,
                "sessions_30d": c.sessions_30d,
                "tenure_days": c.tenure_days,
                "matched_tags": c.matched_tags,
            }
            for c in ranked
        ],
    }


class InviteIn(BaseModel):
    cohort_size: Optional[int] = Field(None, ge=1, le=1000)


@router.post("/releases/{release_id}/invite")
def invite(release_id: int, payload: InviteIn | None = None, db: Session = Depends(db_session)) -> dict[str, Any]:
    r = db.get(FirmwareRelease, release_id)
    if r is None:
        raise HTTPException(status_code=404, detail="release not found")
    return invite_beta_cohort(
        db, r,
        cohort_size=payload.cohort_size if payload else None,
        invited_by="dashboard",
    )


@router.get("/releases/{release_id}/cohort")
def get_cohort(release_id: int, db: Session = Depends(db_session)) -> dict[str, Any]:
    r = db.get(FirmwareRelease, release_id)
    if r is None:
        raise HTTPException(status_code=404, detail="release not found")
    members = db.execute(
        select(BetaCohortMember)
        .where(BetaCohortMember.release_id == release_id)
        .order_by(desc(BetaCohortMember.candidate_score))
    ).scalars().all()
    return {
        "release_id": r.id,
        "version": r.version,
        "members": [
            {
                "device_id": m.device_id,
                "user_id": m.user_id,
                "state": m.state,
                "candidate_score": m.candidate_score,
                "matched_tags": (m.candidate_reason_json or {}).get("matched_tags", []),
                "sessions_30d": (m.candidate_reason_json or {}).get("sessions_30d"),
                "tenure_days": (m.candidate_reason_json or {}).get("tenure_days"),
                "invited_at": m.invited_at.isoformat() if m.invited_at else None,
                "opted_in_at": m.opted_in_at.isoformat() if m.opted_in_at else None,
                "opt_in_source": m.opt_in_source,
                "ota_pushed_at": m.ota_pushed_at.isoformat() if m.ota_pushed_at else None,
                "evaluated_at": m.evaluated_at.isoformat() if m.evaluated_at else None,
                "verdict": m.verdict_json or {},
            }
            for m in members
        ],
    }


# ── Post-deploy verdict (the closing loop) ───────────────────────────


@router.post("/releases/{release_id}/evaluate")
def evaluate(release_id: int, force: bool = False, db: Session = Depends(db_session)) -> dict[str, Any]:
    r = db.get(FirmwareRelease, release_id)
    if r is None:
        raise HTTPException(status_code=404, detail="release not found")
    return evaluate_release(db, r, force=force)


@router.get("/releases/{release_id}/verdict-summary")
def verdict_summary(release_id: int, db: Session = Depends(db_session)) -> dict[str, Any]:
    r = db.get(FirmwareRelease, release_id)
    if r is None:
        raise HTTPException(status_code=404, detail="release not found")
    return {
        "release_id": r.id,
        "version": r.version,
        "status": r.status,
        "beta_report": r.beta_report_json or {},
    }


@router.post("/evaluate-all")
def evaluate_all(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Run the verdict pass across every non-draft release. Manual
    trigger; the scheduler also calls this daily."""
    return run_beta_verdict_pass(db)


# ── Manual OTA-pushed flag (proxy until AWS IoT Jobs is wired) ────────


class OtaMarkIn(BaseModel):
    device_ids: list[str] = Field(default_factory=list)
    mark_all_opted_in: bool = False


@router.post("/releases/{release_id}/mark-ota-pushed")
def mark_ota_pushed(
    release_id: int, payload: OtaMarkIn, db: Session = Depends(db_session)
) -> dict[str, Any]:
    """Proxy for OTA push until AWS IoT Jobs is wired. Flip selected
    members (or every opted-in member) to state=ota_pushed with
    ota_pushed_at=now. Downstream, the verdict pass uses this timestamp
    as the anchor instead of opted_in_at."""
    r = db.get(FirmwareRelease, release_id)
    if r is None:
        raise HTTPException(status_code=404, detail="release not found")
    stmt = select(BetaCohortMember).where(BetaCohortMember.release_id == release_id)
    if payload.mark_all_opted_in:
        stmt = stmt.where(BetaCohortMember.state == "opted_in")
    elif payload.device_ids:
        stmt = stmt.where(BetaCohortMember.device_id.in_(payload.device_ids))
    else:
        raise HTTPException(status_code=400, detail="pass device_ids or mark_all_opted_in=true")
    members = db.execute(stmt).scalars().all()
    now = datetime.now(timezone.utc)
    for m in members:
        m.ota_pushed_at = now
        if m.state == "opted_in":
            m.state = "ota_pushed"
    db.commit()
    return {"ok": True, "flipped": len(members)}


# ── Alpha cohort (employees + R&D grills) ────────────────────────────


def _rekey_synthetic_alpha_ids(db: Session) -> int:
    """Upgrade any alpha cohort members registered with a synthetic
    ``mac:xxxxxxxxxxxx`` device_id to the real telemetry device_id
    hash, once the device has reported stream events.

    Called lazily from ``list_alpha_cohort`` so the upgrade happens as
    data flows in — no separate scheduler step required. Cheap: one
    SELECT per synthetic row. Returns how many rows were re-keyed.
    """
    from sqlalchemy import text
    from app.api.routes.firmware import _device_ids_for_mac

    synthetic = db.execute(
        select(BetaCohortMember)
        .where(BetaCohortMember.opt_in_source == "alpha")
        .where(BetaCohortMember.device_id.like("mac:%"))
    ).scalars().all()
    if not synthetic:
        return 0
    updated = 0
    for m in synthetic:
        mac = m.device_id[4:]
        if len(mac) != 12:
            continue
        real_ids = _device_ids_for_mac(db, mac, limit=1)
        if not real_ids:
            continue
        real = real_ids[0]
        # If a real-keyed row already exists for this (release, device_id),
        # delete the synthetic one to satisfy the unique constraint.
        existing = db.execute(
            select(BetaCohortMember).where(
                BetaCohortMember.release_id == m.release_id,
                BetaCohortMember.device_id == real,
            )
        ).scalars().first()
        if existing is not None:
            db.delete(m)
        else:
            m.device_id = real
        updated += 1
    if updated:
        db.commit()
    return updated


@router.get("/alpha-cohort")
def list_alpha_cohort(db: Session = Depends(db_session)) -> dict[str, Any]:
    """All BetaCohortMembers whose opt-in came via the 'alpha' source.

    Alpha and Beta share the BetaCohortMember schema for now — the
    distinction is carried on the ``opt_in_source`` column. This endpoint
    surfaces the alpha view so the Firmware Hub can show R&D grill
    progress without leaking customer devices onto that tab.

    Side effect: auto-rekeys any synthetic ``mac:xxx`` device_id rows
    to their real telemetry device_id hashes if the grill has come
    back online since the bulk-import registration.
    """
    rekeyed = _rekey_synthetic_alpha_ids(db)

    rows = db.execute(
        select(BetaCohortMember, FirmwareRelease)
        .join(FirmwareRelease, FirmwareRelease.id == BetaCohortMember.release_id)
        .where(BetaCohortMember.opt_in_source == "alpha")
        .order_by(desc(BetaCohortMember.opted_in_at), desc(BetaCohortMember.invited_at))
    ).all()

    members = []
    for m, r in rows:
        members.append({
            "device_id": m.device_id,
            "user_id": m.user_id,
            "state": m.state,
            "candidate_score": m.candidate_score,
            "invited_at": m.invited_at.isoformat() if m.invited_at else None,
            "opted_in_at": m.opted_in_at.isoformat() if m.opted_in_at else None,
            "ota_pushed_at": m.ota_pushed_at.isoformat() if m.ota_pushed_at else None,
            "evaluated_at": m.evaluated_at.isoformat() if m.evaluated_at else None,
            "release_id": r.id,
            "release_version": r.version,
            "release_title": r.title,
            "release_status": r.status,
        })

    # State tally
    by_state: dict[str, int] = {}
    for m in members:
        by_state[m["state"]] = by_state.get(m["state"], 0) + 1

    return {
        "members": members,
        "count": len(members),
        "state_distribution": by_state,
        "rekeyed_synthetic_ids": rekeyed,
    }


# ── Alpha cohort · bulk historical import ────────────────────────────


class AlphaImportEntry(BaseModel):
    """One MAC to register. Accepts any common MAC format (colons,
    dashes, no separators, mixed case); it's normalized server-side."""
    mac: str = Field(..., max_length=32)
    user_id: Optional[str] = Field(None, max_length=128)
    # Optional override — if set, we pin the device to this firmware
    # version instead of auto-detecting from telemetry. Useful when a
    # device hasn't phoned home in a while but we know what it's on.
    firmware_version_override: Optional[str] = Field(None, max_length=64)


class AlphaBulkImportIn(BaseModel):
    entries: list[AlphaImportEntry] = Field(default_factory=list)
    dry_run: bool = False
    # Default notes stamped onto auto-created historical releases.
    release_notes: Optional[str] = Field(
        default=(
            "[HISTORICAL IMPORT] Firmware was already running on field "
            "devices before dashboard registration. Do NOT use this "
            "release record to initiate a new OTA push — it has no "
            "binary attached. Created by alpha cohort bulk import."
        ),
        max_length=2048,
    )


@router.post("/alpha-cohort/bulk-import")
def alpha_bulk_import(
    payload: AlphaBulkImportIn,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Bulk-register alpha testers without triggering a new firmware
    release.

    For each MAC:
      1. Normalize + resolve to the device_id hashes that have reported
         under it.
      2. Detect current firmware version from the latest stream event
         (unless ``firmware_version_override`` is provided).
      3. Auto-create a FirmwareRelease row for that version if missing,
         with status='ga', approved_for_alpha=True, and a historical-
         import marker in notes. No binary, no OTA capability — this
         is a registration-only record.
      4. Insert a BetaCohortMember with opt_in_source='alpha' and
         state='ota_pushed' (the device is already on the firmware),
         idempotent by the unique (release_id, device_id) constraint.

    The device's historical telemetry is already pulled by the regular
    telemetry pipeline, so no separate backfill is needed — registration
    unlocks the analytics surfaces, that's all.

    Dashboard deploy flows (beta / gamma) continue to work for this
    cohort: the members are regular ``state='ota_pushed'`` rows, so
    inviting them to a *new* release uses the standard invite + OTA
    path.
    """
    # Import here to avoid a cycle (firmware route imports from services).
    from sqlalchemy import text
    from app.api.routes.firmware import (
        _MAC_EXPR,
        _device_ids_for_mac,
        normalize_mac,
    )
    from app.models import AppSideDeviceObservation

    now = datetime.now(timezone.utc)
    release_cache: dict[str, FirmwareRelease] = {}
    releases_created: list[str] = []

    # Preload every firmware release version → row for fast lookup.
    existing_releases = db.execute(select(FirmwareRelease)).scalars().all()
    for r in existing_releases:
        release_cache[r.version] = r

    def _ensure_release(version: str) -> FirmwareRelease:
        if version in release_cache:
            return release_cache[version]
        # Semver-ish title from version: "Alpha 01.01.95"
        r = FirmwareRelease(
            version=version,
            title=f"Alpha {version}",
            notes=payload.release_notes,
            addresses_issues=[],
            status="ga",
            beta_cohort_target_size=100,
            approved_for_alpha=True,
            approval_audit_json=[{
                "event": "historical_import",
                "at": now.isoformat(),
                "by": "dashboard:alpha-bulk-import",
                "note": "Auto-created to hold historical alpha cohort membership.",
            }],
            created_by="dashboard:alpha-bulk-import",
            released_at=now,
        )
        db.add(r)
        db.flush()  # need the PK for BetaCohortMember.release_id
        release_cache[version] = r
        releases_created.append(version)
        return r

    results: list[dict[str, Any]] = []
    by_firmware: dict[str, int] = {}
    successful = 0
    already_registered = 0
    invalid_macs: list[str] = []
    unknown_firmware: list[str] = []
    # MACs resolved only via app-side observations (no live stream data).
    # Registered under a synthetic `mac:xxx` device_id so they aren't lost;
    # re-keying to the real device_id happens automatically the first time
    # the device reports telemetry.
    app_side_only: list[str] = []

    for entry in payload.entries:
        raw_mac = (entry.mac or "").strip()
        mac = normalize_mac(raw_mac)
        if mac is None:
            invalid_macs.append(raw_mac)
            results.append({
                "input_mac": raw_mac,
                "status": "invalid_mac",
            })
            continue

        device_ids = _device_ids_for_mac(db, mac)
        # Telemetry source used for firmware detection (for result reporting).
        source: str = "stream"
        fw_version: Optional[str] = entry.firmware_version_override
        first_seen_on_version: Optional[datetime] = None

        if fw_version is None and device_ids:
            # Preferred: last firmware seen in the live stream window.
            row = db.execute(text(
                f"""
                SELECT firmware_version, MIN(sample_timestamp) AS first_seen
                FROM telemetry_stream_events
                WHERE {_MAC_EXPR} = :mac
                  AND firmware_version IS NOT NULL
                GROUP BY firmware_version
                ORDER BY MAX(sample_timestamp) DESC NULLS LAST
                LIMIT 1
                """
            ), {"mac": mac}).first()
            if row is not None:
                fw_version = row[0]
                first_seen_on_version = row[1]

        # Fallback: app-side device observations. Stream events retain
        # only ~7d, so alpha testers who haven't cooked recently fall
        # through to this path. AppSideDeviceObservation keeps much
        # longer history via Freshdesk + app sync.
        if fw_version is None:
            obs = db.execute(
                select(AppSideDeviceObservation)
                .where(AppSideDeviceObservation.mac_normalized == mac)
                .where(AppSideDeviceObservation.firmware_version.is_not(None))
                .order_by(desc(AppSideDeviceObservation.observed_at))
                .limit(1)
            ).scalars().first()
            if obs is not None:
                fw_version = obs.firmware_version
                first_seen_on_version = obs.observed_at
                if not device_ids:
                    source = "app_side"

        if not fw_version:
            unknown_firmware.append(mac)
            results.append({
                "input_mac": raw_mac,
                "mac": mac,
                "device_id_count": len(device_ids),
                "status": "unknown_firmware",
                "note": "No firmware detected in stream events or app-side observations. Pass firmware_version_override to force a version.",
            })
            continue

        release = _ensure_release(fw_version)
        by_firmware[fw_version] = by_firmware.get(fw_version, 0) + 1

        # If we had no device_ids, fall back to synthetic `mac:` id so the
        # MAC is tracked; the telemetry re-keyer will link it up when the
        # device comes back online.
        target_device_ids = device_ids or [f"mac:{mac}"]
        if not device_ids:
            app_side_only.append(mac)

        if payload.dry_run:
            successful += 1
            results.append({
                "input_mac": raw_mac,
                "mac": mac,
                "device_id_count": len(device_ids),
                "firmware_version": fw_version,
                "firmware_source": source,
                "release_id": release.id,
                "first_seen_on_version": first_seen_on_version.isoformat() if first_seen_on_version else None,
                "status": "would_register",
                "user_id": entry.user_id,
            })
            continue

        # Insert a cohort member per device_id (a physical grill can map
        # to multiple device_id hashes if it was paired with multiple
        # user accounts). Upsert via ON CONFLICT DO NOTHING semantics.
        created_for_device = 0
        for did in target_device_ids:
            exists = db.execute(
                select(BetaCohortMember).where(
                    BetaCohortMember.release_id == release.id,
                    BetaCohortMember.device_id == did,
                )
            ).scalars().first()
            if exists is not None:
                already_registered += 1
                continue
            member = BetaCohortMember(
                release_id=release.id,
                device_id=did,
                user_id=entry.user_id,
                candidate_score=None,
                candidate_reason_json={
                    "historical_import": True,
                    "imported_from_mac": mac,
                    "firmware_source": source,
                    "first_seen_on_version": first_seen_on_version.isoformat() if first_seen_on_version else None,
                    "note": "Registered via alpha-cohort bulk import; device was already running this firmware before dashboard registration.",
                },
                state="ota_pushed",
                invited_at=now,
                opted_in_at=now,
                opt_in_source="alpha",
                ota_pushed_at=first_seen_on_version or now,
                ota_confirmed_at=first_seen_on_version or now,
            )
            db.add(member)
            created_for_device += 1

        successful += 1
        results.append({
            "input_mac": raw_mac,
            "mac": mac,
            "device_id_count": len(device_ids),
            "firmware_version": fw_version,
            "firmware_source": source,
            "release_id": release.id,
            "first_seen_on_version": first_seen_on_version.isoformat() if first_seen_on_version else None,
            "status": "registered",
            "cohort_rows_inserted": created_for_device,
            "user_id": entry.user_id,
        })

    if payload.dry_run:
        db.rollback()
    else:
        db.commit()

    return {
        "dry_run": payload.dry_run,
        "total_requested": len(payload.entries),
        "successful": successful,
        "by_firmware_version": by_firmware,
        "releases_created": releases_created,
        "invalid_macs": invalid_macs,
        "unknown_firmware": unknown_firmware,
        "app_side_only": app_side_only,
        "already_registered": already_registered,
        "results": results,
    }


# ── Alpha cohort · per-device firmware timeline ──────────────────────


@router.get("/alpha-cohort/{mac}/firmware-timeline")
def alpha_firmware_timeline(mac: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    """Firmware-version journey for a single alpha tester device.

    Returns one row per version the MAC has been observed on, with
    first-seen / last-seen timestamps and a session count. Lets the
    dashboard show "this grill ran 01.01.90 for 11 cooks before moving
    to 01.01.92…" etc.
    """
    from sqlalchemy import text
    from app.api.routes.firmware import _MAC_EXPR, _device_ids_for_mac, normalize_mac

    normalized = normalize_mac(mac)
    if normalized is None:
        raise HTTPException(status_code=400, detail="invalid MAC")
    device_ids = _device_ids_for_mac(db, normalized)

    # Stream-event-derived version transitions.
    rows = db.execute(text(
        f"""
        SELECT firmware_version,
               MIN(sample_timestamp) AS first_seen,
               MAX(sample_timestamp) AS last_seen,
               COUNT(DISTINCT CASE WHEN engaged IS TRUE THEN DATE_TRUNC('day', sample_timestamp) END) AS active_days,
               COUNT(*) AS sample_count
        FROM telemetry_stream_events
        WHERE {_MAC_EXPR} = :mac
          AND firmware_version IS NOT NULL
        GROUP BY firmware_version
        ORDER BY MIN(sample_timestamp) ASC
        """
    ), {"mac": normalized}).all()

    # Session counts per firmware (TelemetrySession has deeper retention
    # than telemetry_stream_events, so this pair is the richest view).
    session_rows: list[tuple[str, int, Optional[datetime], Optional[datetime]]] = []
    if device_ids:
        # SQLAlchemy 2.0 tuple select keeps the result ordered + typed.
        from app.models import TelemetrySession as _TelemetrySession
        session_rows = list(db.execute(
            select(
                _TelemetrySession.firmware_version,
                func.count(_TelemetrySession.id),
                func.min(_TelemetrySession.session_start),
                func.max(_TelemetrySession.session_end),
            )
            .where(_TelemetrySession.device_id.in_(device_ids))
            .where(_TelemetrySession.firmware_version.is_not(None))
            .group_by(_TelemetrySession.firmware_version)
            .order_by(func.min(_TelemetrySession.session_start))
        ).all())
    session_by_version = {
        (row[0] or "unknown"): {
            "session_count": int(row[1] or 0),
            "first_session_at": row[2].isoformat() if row[2] else None,
            "last_session_at": row[3].isoformat() if row[3] else None,
        }
        for row in session_rows
    }

    versions = []
    for row in rows:
        version = row[0] or "unknown"
        sessions = session_by_version.get(version, {"session_count": 0, "first_session_at": None, "last_session_at": None})
        versions.append({
            "firmware_version": version,
            "stream_first_seen": row[1].isoformat() if row[1] else None,
            "stream_last_seen": row[2].isoformat() if row[2] else None,
            "stream_active_days": int(row[3] or 0),
            "stream_sample_count": int(row[4] or 0),
            **sessions,
        })

    return {
        "mac": normalized,
        "device_id_count": len(device_ids),
        "versions": versions,
    }


# ── Alpha cohort · analytics vs fleet ────────────────────────────────


@router.get("/alpha-cohort/analytics")
def alpha_cohort_analytics(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Comparison view: alpha cohort (by firmware) vs. the rest of the
    production fleet on 01.01.33 / 01.01.34.

    Returns summary rows of cook success, stability, overshoot, and
    disconnect proxy rate, segmented by firmware version and whether
    the device is a registered alpha member.
    """
    from app.models import TelemetrySession as _TelemetrySession

    # Alpha device_ids (everything in BetaCohortMember with opt_in_source='alpha').
    alpha_device_ids = set(
        row[0] for row in db.execute(
            select(BetaCohortMember.device_id).where(BetaCohortMember.opt_in_source == "alpha")
        ).all()
        if row[0] and not (row[0] or "").startswith("mac:")
    )

    # Pull aggregate stats per (firmware_version, is_alpha).
    #
    # We look at last 180 days of sessions to make the comparison
    # meaningful — enough history for alpha to cover 01.01.90 onward,
    # while keeping the fleet-baseline current.
    window_start = datetime.now(timezone.utc) - __import__("datetime").timedelta(days=180)

    # Fetch everything in one query + group in Python (segmentation by
    # alpha membership is a set-contains check, awkward to do in SQL).
    rows = db.execute(
        select(
            _TelemetrySession.firmware_version,
            _TelemetrySession.device_id,
            _TelemetrySession.cook_success,
            _TelemetrySession.disconnect_events,
            _TelemetrySession.max_overshoot_f,
            _TelemetrySession.in_control_pct,
            _TelemetrySession.temp_stability_score,
            _TelemetrySession.time_to_stabilization_seconds,
        )
        .where(_TelemetrySession.session_start >= window_start)
        .where(_TelemetrySession.firmware_version.is_not(None))
    ).all()

    # Key: (firmware_version, is_alpha)
    buckets: dict[tuple[str, bool], dict[str, Any]] = {}
    for r in rows:
        fw = r[0] or "unknown"
        is_alpha = r[1] in alpha_device_ids
        key = (fw, is_alpha)
        b = buckets.setdefault(key, {
            "sessions": 0,
            "successes": 0,
            "disconnect_events": 0,
            "overshoot_samples": [],
            "in_control_samples": [],
            "stability_samples": [],
            "stabilize_samples": [],
            "device_ids": set(),
        })
        b["sessions"] += 1
        if r[2]:
            b["successes"] += 1
        b["disconnect_events"] += int(r[3] or 0)
        if r[4] is not None:
            b["overshoot_samples"].append(float(r[4]))
        if r[5] is not None:
            b["in_control_samples"].append(float(r[5]))
        if r[6] is not None:
            b["stability_samples"].append(float(r[6]))
        if r[7] is not None:
            b["stabilize_samples"].append(float(r[7]))
        b["device_ids"].add(r[1])

    def _mean(xs: list[float]) -> float | None:
        if not xs:
            return None
        return sum(xs) / len(xs)

    def _pct(xs: list[float]) -> float | None:
        if not xs:
            return None
        return sum(xs) / len(xs)

    segments = []
    for (fw, is_alpha), b in sorted(buckets.items(), key=lambda kv: (kv[0][1] is False, kv[0][0])):
        success_rate = b["successes"] / b["sessions"] if b["sessions"] else None
        segments.append({
            "firmware_version": fw,
            "cohort": "alpha" if is_alpha else "production",
            "sessions": b["sessions"],
            "devices": len(b["device_ids"]),
            "cook_success_rate": success_rate,
            "avg_disconnects_per_session": b["disconnect_events"] / b["sessions"] if b["sessions"] else None,
            "avg_max_overshoot_f": _mean(b["overshoot_samples"]),
            "avg_in_control_pct": _pct(b["in_control_samples"]),
            "avg_stability_score": _mean(b["stability_samples"]),
            "avg_time_to_stabilize_seconds": _mean(b["stabilize_samples"]),
        })

    return {
        "window_days": 180,
        "alpha_device_id_count": len(alpha_device_ids),
        "segments": segments,
    }


# ── Alpha cohort · trend (version-over-version journey) ─────────────


def _alpha_device_ids(db: Session) -> set[str]:
    rows = db.execute(
        select(BetaCohortMember.device_id).where(BetaCohortMember.opt_in_source == "alpha")
    ).all()
    return {r[0] for r in rows if r[0] and not str(r[0]).startswith("mac:")}


def _version_sort_key(v: str) -> tuple[int, ...]:
    """Sort '01.01.90' < '01.01.95' < '01.01.99' < '01.01.100' correctly."""
    try:
        return tuple(int(p) for p in v.split(".") if p.isdigit())
    except ValueError:
        return (0, 0, 0)


@router.get("/alpha-cohort/trend")
def alpha_cohort_trend(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Chronological journey across alpha firmware versions, with a
    production baseline overlay.

    Returns:
      * points[]: ordered alpha-cohort metric rows keyed by firmware
        version (90, 91, 92, … 99). Each row carries sample size + all
        the headline metrics so the UI can draw multi-line charts.
      * production_baseline{}: aggregate metrics over production
        fleet versions 01.01.33 and 01.01.34 from the same window.
        Gives us the "are we beating status quo?" horizontal line.
      * window_days: the session lookback we used.
    """
    from app.models import TelemetrySession as _TelemetrySession

    window_days = 180
    window_start = datetime.now(timezone.utc) - timedelta(days=window_days)
    alpha_ids = _alpha_device_ids(db)

    # Pull the per-session fields we aggregate.
    session_rows = db.execute(
        select(
            _TelemetrySession.firmware_version,
            _TelemetrySession.device_id,
            _TelemetrySession.cook_success,
            _TelemetrySession.disconnect_events,
            _TelemetrySession.max_overshoot_f,
            _TelemetrySession.in_control_pct,
            _TelemetrySession.temp_stability_score,
            _TelemetrySession.time_to_stabilization_seconds,
            _TelemetrySession.error_count,
        )
        .where(_TelemetrySession.session_start >= window_start)
        .where(_TelemetrySession.firmware_version.is_not(None))
    ).all()

    # Bucket per (firmware_version, is_alpha)
    alpha_buckets: dict[str, dict[str, Any]] = {}
    prod_buckets: dict[str, dict[str, Any]] = {}

    def _mk() -> dict[str, Any]:
        return {
            "sessions": 0, "successes": 0, "disconnects": 0, "error_events": 0,
            "overshoot": [], "in_control": [], "stability": [], "stabilize": [],
            "devices": set(),
        }

    for r in session_rows:
        fw = r[0] or "unknown"
        did = r[1]
        is_alpha = did in alpha_ids
        target = alpha_buckets if is_alpha else prod_buckets
        b = target.setdefault(fw, _mk())
        b["sessions"] += 1
        if r[2]:
            b["successes"] += 1
        b["disconnects"] += int(r[3] or 0)
        b["error_events"] += int(r[8] or 0)
        if r[4] is not None:
            b["overshoot"].append(float(r[4]))
        if r[5] is not None:
            b["in_control"].append(float(r[5]))
        if r[6] is not None:
            b["stability"].append(float(r[6]))
        if r[7] is not None:
            b["stabilize"].append(float(r[7]))
        b["devices"].add(did)

    def _avg(xs: list[float]) -> Optional[float]:
        return (sum(xs) / len(xs)) if xs else None

    def _summarize(b: dict[str, Any]) -> dict[str, Any]:
        n = b["sessions"]
        return {
            "sessions": n,
            "devices": len(b["devices"]),
            "cook_success_rate": (b["successes"] / n) if n else None,
            "avg_disconnects_per_session": (b["disconnects"] / n) if n else None,
            "avg_error_events_per_session": (b["error_events"] / n) if n else None,
            "avg_max_overshoot_f": _avg(b["overshoot"]),
            "avg_in_control_pct": _avg(b["in_control"]),
            "avg_stability_score": _avg(b["stability"]),
            "avg_time_to_stabilize_seconds": _avg(b["stabilize"]),
            # Small-sample flag — <10 devices or <20 sessions means
            # don't draw strong conclusions.
            "small_sample": (len(b["devices"]) < 10) or (n < 20),
        }

    # Alpha journey — chronologically ordered.
    alpha_points = [
        {"firmware_version": fw, **_summarize(b)}
        for fw, b in sorted(alpha_buckets.items(), key=lambda kv: _version_sort_key(kv[0]))
    ]

    # Production baseline from 01.01.33 + 01.01.34 combined.
    prod_baseline_versions = ("01.01.33", "01.01.34")
    combined: dict[str, Any] = _mk()
    for v in prod_baseline_versions:
        b = prod_buckets.get(v)
        if not b:
            continue
        combined["sessions"] += b["sessions"]
        combined["successes"] += b["successes"]
        combined["disconnects"] += b["disconnects"]
        combined["error_events"] += b["error_events"]
        combined["overshoot"] += b["overshoot"]
        combined["in_control"] += b["in_control"]
        combined["stability"] += b["stability"]
        combined["stabilize"] += b["stabilize"]
        combined["devices"] |= b["devices"]

    production_baseline = {
        "versions": list(prod_baseline_versions),
        **_summarize(combined),
    }

    return {
        "window_days": window_days,
        "alpha_device_id_count": len(alpha_ids),
        "points": alpha_points,
        "production_baseline": production_baseline,
    }


# ── Alpha cohort · per-version error patterns ───────────────────────


@router.get("/alpha-cohort/error-patterns")
def alpha_cohort_error_patterns(
    top_n: int = 5,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Top error codes per alpha firmware version. Uses
    TelemetrySession.error_codes_json (list-of-strings) and counts
    incidence per code, returning the top N per version.
    """
    from app.models import TelemetrySession as _TelemetrySession

    alpha_ids = _alpha_device_ids(db)
    if not alpha_ids:
        return {"versions": []}

    window_start = datetime.now(timezone.utc) - timedelta(days=180)
    rows = db.execute(
        select(
            _TelemetrySession.firmware_version,
            _TelemetrySession.error_codes_json,
        )
        .where(_TelemetrySession.session_start >= window_start)
        .where(_TelemetrySession.firmware_version.is_not(None))
        .where(_TelemetrySession.device_id.in_(alpha_ids))
    ).all()

    # fw_version → {code: count}, plus session totals for % incidence
    per_version: dict[str, dict[str, int]] = {}
    session_totals: dict[str, int] = {}
    for fw, codes in rows:
        fw = fw or "unknown"
        session_totals[fw] = session_totals.get(fw, 0) + 1
        if not codes:
            continue
        v = per_version.setdefault(fw, {})
        for code in codes:
            if code is None:
                continue
            key = str(code)
            v[key] = v.get(key, 0) + 1

    versions = []
    for fw in sorted(session_totals.keys(), key=_version_sort_key):
        total = session_totals[fw]
        codes = per_version.get(fw, {})
        ranked = sorted(codes.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
        versions.append({
            "firmware_version": fw,
            "sessions": total,
            "error_free_sessions_pct": (
                (total - sum(codes.values())) / total if total else None
            ),
            "top_error_codes": [
                {"code": code, "occurrences": count, "incidence_pct": count / total if total else None}
                for code, count in ranked
            ],
        })

    return {"versions": versions, "window_days": 180}


# ── Alpha cohort · Opus 4.7 narrative insight ────────────────────────


_ALPHA_INSIGHT_CACHE: dict[str, Any] = {"generated_at": None, "payload": None}


class AlphaInsightObservation(BaseModel):
    title: str = Field(description="Short 4-8 word headline.")
    detail: str = Field(description="One paragraph (2-4 sentences) on what the data shows.")
    recommendation: str = Field(description="One concrete next action — who, what, by when.")
    severity: str = Field(description="'improving' | 'regressing' | 'investigate' | 'info'")
    firmware_versions_cited: list[str] = Field(default_factory=list)


class AlphaInsightBundle(BaseModel):
    overall_theme: str = Field(description="One-sentence headline for the whole alpha program state.")
    observations: list[AlphaInsightObservation] = Field(description="3-5 observations, ordered by urgency.")


ALPHA_INSIGHT_SYSTEM_PROMPT = """You are the firmware program lead at Spider Grills,
a premium BBQ-controller company whose Venom controller runs thousands of pellet grills
in the field. Right now the engineering team is running an alpha program: firmware
versions 01.01.90 → 01.01.99, tested on a small set of internal + opt-in devices.
Production fleet is on 01.01.33 and 01.01.34.

Your job: read the per-version metrics + error patterns for the alpha cohort and write
3–5 ACTIONABLE observations. Think like a program lead, not a dashboard narrator —
every observation should name a specific firmware version, a specific metric, and a
specific next action.

How to read the data:
- `points[]` is the alpha cohort's version journey (90 → 99).
- `production_baseline` is 01.01.33/34 combined — the "status quo" we must beat.
- `cook_success_rate`, `avg_in_control_pct`, `avg_stability_score` — higher is better.
- `avg_disconnects_per_session`, `avg_max_overshoot_f`, `avg_time_to_stabilize_seconds`,
  `avg_error_events_per_session` — lower is better.
- `small_sample=true` means <10 devices or <20 sessions. Don't make strong claims from
  these; call the small sample out explicitly when citing them.

What to output:
- `overall_theme`: one sentence, "alpha is trending better / alpha regressed at N / mixed."
- For each observation:
  - `severity`: 'improving' (showing clear gain vs baseline or earlier version),
                 'regressing' (worse than the prior version or baseline by a meaningful margin),
                 'investigate' (anomaly that needs a human to look at before shipping),
                 'info' (context-setting observation worth knowing but not acting on today).
  - `title`: a headline like "01.01.97 doubled disconnects vs 01.01.95"
  - `detail`: 2-4 sentences citing the actual numbers.
  - `recommendation`: concrete action. "Matías: bisect 01.01.95 → 97 for the WiFi
                       reconnect regression. Target fix in 01.01.100."

Bad example (too generic): "Cook success is up this year."
Good example: "01.01.95 lifted cook success to 71% (n=42 sessions, 4 devices) vs
              01.01.93's 58% — a 13pp gain. Production baseline is 68%. The gain held
              through 01.01.99 (74%). Recommendation: if no regression emerges in the
              next week, flag 01.01.99 as a candidate for beta promotion."

Return ONLY the structured output. No preamble, no prose wrapper."""


@router.post("/alpha-cohort/insight/regenerate")
def alpha_insight_regenerate(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Trigger an Opus 4.7 pass and cache the result. Expensive (one
    1M-context Opus call); use the GET /insight for cache-reads."""
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured")

    # Pull the same context the dashboard shows: trend + error patterns.
    trend = alpha_cohort_trend(db)
    errors = alpha_cohort_error_patterns(top_n=5, db=db)
    if not trend["points"]:
        raise HTTPException(status_code=400, detail="No alpha sessions yet — run some cooks before asking Opus to analyze.")

    import anthropic
    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        timeout=180,
        max_retries=1,
    )
    user_msg = (
        "Here is the current state of the Spider Grills alpha firmware program.\n\n"
        "ALPHA JOURNEY (version-ordered):\n"
        + json.dumps(trend, default=str, indent=2)
        + "\n\nERROR PATTERNS PER ALPHA VERSION:\n"
        + json.dumps(errors, default=str, indent=2)
        + "\n\nGenerate the overall_theme + 3-5 observations."
    )

    started = datetime.now(timezone.utc)
    try:
        response = client.messages.parse(
            model="claude-opus-4-7",
            max_tokens=16000,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            system=[{
                "type": "text",
                "text": ALPHA_INSIGHT_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_msg}],
            output_format=AlphaInsightBundle,
        )
    except Exception as exc:
        logger.exception("alpha insight Opus call failed")
        raise HTTPException(status_code=502, detail=f"Opus call failed: {exc}")

    bundle: Optional[AlphaInsightBundle] = response.parsed_output
    if bundle is None:
        raise HTTPException(status_code=502, detail="Opus returned no parsed output")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": "claude-opus-4-7",
        "overall_theme": bundle.overall_theme,
        "observations": [o.model_dump() for o in bundle.observations],
        "duration_ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
    }
    _ALPHA_INSIGHT_CACHE["generated_at"] = payload["generated_at"]
    _ALPHA_INSIGHT_CACHE["payload"] = payload
    return payload


@router.get("/alpha-cohort/insight")
def alpha_insight_get(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Return the latest cached Opus narrative. If nothing cached yet,
    returns a 404-style empty shell so the UI can prompt for first run."""
    payload = _ALPHA_INSIGHT_CACHE.get("payload")
    if not payload:
        return {
            "generated_at": None,
            "overall_theme": None,
            "observations": [],
            "cached": False,
        }
    return {**payload, "cached": True}


# ── Gamma waves (production rollout) ─────────────────────────────────


@router.get("/gamma-status")
def gamma_status(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Releases that have kicked off (or are planning) Gamma waves.

    A Gamma rollout is a sequence of AWS IoT Jobs that stage the push
    across production at ~10%/day. We store the planned wave shape in
    ``gamma_plan_json`` and the actual job IDs in
    ``gamma_iot_job_ids_json``. This endpoint joins those so the UI can
    show: planned device count per wave, wave day, IoT job status
    (if any), and the overall release health.
    """
    rows = db.execute(
        select(FirmwareRelease)
        .where(FirmwareRelease.approved_for_gamma.is_(True))
        .order_by(desc(FirmwareRelease.released_at), desc(FirmwareRelease.created_at))
    ).scalars().all()

    releases = []
    for r in rows:
        plan = r.gamma_plan_json or {}
        job_ids = r.gamma_iot_job_ids_json or []
        waves_raw = plan.get("waves") if isinstance(plan, dict) else None
        waves: list[dict[str, Any]] = []
        if isinstance(waves_raw, list):
            for i, w in enumerate(waves_raw):
                if not isinstance(w, dict):
                    continue
                waves.append({
                    "wave_index": i + 1,
                    "target_pct": w.get("target_pct"),
                    "target_devices": w.get("target_devices"),
                    "scheduled_at": w.get("scheduled_at"),
                    "started_at": w.get("started_at"),
                    "completed_at": w.get("completed_at"),
                    "aws_job_id": job_ids[i] if i < len(job_ids) else None,
                    "status": w.get("status") or ("pending" if i >= len(job_ids) else "unknown"),
                })
        releases.append({
            "release_id": r.id,
            "version": r.version,
            "title": r.title,
            "status": r.status,
            "approved_for_gamma": r.approved_for_gamma,
            "approved_at": r.approved_at.isoformat() if r.approved_at else None,
            "released_at": r.released_at.isoformat() if r.released_at else None,
            "target_controller_model": r.target_controller_model,
            "waves": waves,
            "total_planned": sum(w.get("target_devices") or 0 for w in waves),
            "aws_job_id_count": len(job_ids),
        })

    return {"releases": releases, "count": len(releases)}


# ── Public opt-in (unauthed, per-device) ─────────────────────────────


class OptInIn(BaseModel):
    device_id: str
    release_id: int
    source: str = "web"


@public_router.post("/opt-in")
def opt_in(payload: OptInIn, db: Session = Depends(db_session)) -> dict[str, Any]:
    """User-facing opt-in. Proper token-based auth to come post-Agustin
    review; for now any device_id that's been invited to this release
    can opt in."""
    return record_opt_in(
        db, release_id=payload.release_id, device_id=payload.device_id, source=payload.source
    )


@public_router.post("/decline")
def decline(payload: OptInIn, db: Session = Depends(db_session)) -> dict[str, Any]:
    return record_decline(db, release_id=payload.release_id, device_id=payload.device_id)
