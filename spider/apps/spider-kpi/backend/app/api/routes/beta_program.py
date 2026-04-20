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
    return {"tags": [_tag_row(t) for t in rows]}


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
