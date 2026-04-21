"""AI feedback + self-grade routes.

Closes the loop on AI-generated artifacts: every insight, DECI draft,
issue-signal classification, and firmware verdict gets a one-click
reaction (acted_on / already_knew / wrong / ignore) captured here.

The weekly ``ai_self_grade`` run consumes these reactions to compute
per-source precision and propose a ``prompt_delta`` for the insight
engine. ``prompt_delta`` is never auto-applied — Joseph has to approve
each one explicitly to prevent Opus from training itself on its own
preferences unsupervised.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.api.routes.auth import get_user_from_request
from app.models import AIFeedback, AISelfGrade, AuthUser


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai", tags=["ai-feedback"])


OWNER_EMAIL = "joseph@spidergrills.com"
VALID_ARTIFACT_TYPES = {"ai_insight", "deci_draft", "issue_signal", "firmware_verdict"}
VALID_REACTIONS = {"acted_on", "already_knew", "wrong", "ignore"}


def _require_user(request: Request, db: Session) -> AuthUser:
    user = get_user_from_request(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Dashboard session required")
    return user


# ── feedback capture ────────────────────────────────────────────────────


class FeedbackBody(BaseModel):
    artifact_type: str = Field(..., max_length=40)
    artifact_id: str = Field(..., max_length=80)
    reaction: str = Field(..., max_length=20)
    note: Optional[str] = Field(None, max_length=2000)


@router.post("/feedback")
def post_feedback(
    body: FeedbackBody,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    user = _require_user(request, db)
    if body.artifact_type not in VALID_ARTIFACT_TYPES:
        raise HTTPException(status_code=400, detail=f"artifact_type must be one of {sorted(VALID_ARTIFACT_TYPES)}")
    if body.reaction not in VALID_REACTIONS:
        raise HTTPException(status_code=400, detail=f"reaction must be one of {sorted(VALID_REACTIONS)}")

    email = (user.email or "").lower()
    existing = db.execute(
        select(AIFeedback)
        .where(AIFeedback.user_email == email)
        .where(AIFeedback.artifact_type == body.artifact_type)
        .where(AIFeedback.artifact_id == body.artifact_id)
    ).scalars().first()

    if existing:
        existing.reaction = body.reaction
        if body.note is not None:
            existing.note = body.note
        existing.updated_at = datetime.now(timezone.utc)
        row = existing
    else:
        row = AIFeedback(
            user_email=email,
            artifact_type=body.artifact_type,
            artifact_id=body.artifact_id,
            reaction=body.reaction,
            note=body.note,
        )
        db.add(row)
    db.commit()
    return {
        "ok": True,
        "id": row.id,
        "artifact_type": row.artifact_type,
        "artifact_id": row.artifact_id,
        "reaction": row.reaction,
    }


@router.get("/feedback/mine")
def my_feedback(
    artifact_type: Optional[str] = None,
    request: Request = None,  # type: ignore
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Return the current user's reactions so UI can render the right pill
    state without a round-trip per artifact."""
    user = _require_user(request, db)
    email = (user.email or "").lower()
    q = select(AIFeedback).where(AIFeedback.user_email == email)
    if artifact_type:
        q = q.where(AIFeedback.artifact_type == artifact_type)
    rows = db.execute(q.order_by(desc(AIFeedback.updated_at)).limit(500)).scalars().all()
    return {
        "reactions": [
            {
                "artifact_type": r.artifact_type,
                "artifact_id": r.artifact_id,
                "reaction": r.reaction,
                "note": r.note,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ],
    }


@router.get("/feedback/summary")
def feedback_summary(
    window_days: int = 30,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Precision rollup per (artifact_type, reaction). Public within the
    dashboard — any signed-in user can see the org-wide numbers."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    rows = db.execute(
        select(AIFeedback.artifact_type, AIFeedback.reaction, func.count(AIFeedback.id))
        .where(AIFeedback.updated_at >= cutoff)
        .group_by(AIFeedback.artifact_type, AIFeedback.reaction)
    ).all()
    by_type: dict[str, dict[str, int]] = {}
    for artifact_type, reaction, count in rows:
        by_type.setdefault(artifact_type, {})[reaction] = int(count)
    # Precision per source: acted_on / (acted_on + already_knew + wrong + ignore)
    # Precision-weighted: acted_on gets full credit, already_knew gets half,
    # wrong + ignore count as misses. Gives us a single number per source.
    rollup: dict[str, dict[str, Any]] = {}
    for atype, counts in by_type.items():
        acted = counts.get("acted_on", 0)
        knew = counts.get("already_knew", 0)
        wrong = counts.get("wrong", 0)
        ignore = counts.get("ignore", 0)
        total = acted + knew + wrong + ignore
        if total == 0:
            continue
        score = (acted + 0.5 * knew) / total
        rollup[atype] = {
            "counts": counts,
            "total": total,
            "precision_score": round(score, 3),
        }
    return {
        "window_days": window_days,
        "by_type": rollup,
    }


# ── self-grade (owner-only controls) ────────────────────────────────────


@router.get("/self-grade")
def list_self_grades(
    limit: int = 12,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    rows = db.execute(
        select(AISelfGrade).order_by(desc(AISelfGrade.run_at)).limit(limit)
    ).scalars().all()
    return {
        "grades": [_serialize_grade(r) for r in rows],
    }


@router.get("/self-grade/{grade_id}")
def get_self_grade(grade_id: int, db: Session = Depends(db_session)) -> dict[str, Any]:
    row = db.get(AISelfGrade, grade_id)
    if row is None:
        raise HTTPException(status_code=404, detail="self-grade not found")
    return _serialize_grade(row)


@router.post("/self-grade/run")
def run_self_grade(
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Manual trigger — owner-only. Normally runs Sunday 10:00 ET via the
    scheduler."""
    user = _require_user(request, db)
    if (user.email or "").lower() != OWNER_EMAIL:
        raise HTTPException(status_code=403, detail="Owner only")
    from app.services.ai_self_grade import run_weekly_self_grade
    result = run_weekly_self_grade(db)
    return result


@router.post("/self-grade/{grade_id}/approve")
def approve_prompt_delta(
    grade_id: int,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Owner approves the Opus-proposed prompt_delta for this run. Does
    NOT yet apply it — that's a separate action so you can approve the
    text and then decide when to fold it into production."""
    user = _require_user(request, db)
    if (user.email or "").lower() != OWNER_EMAIL:
        raise HTTPException(status_code=403, detail="Owner only")
    row = db.get(AISelfGrade, grade_id)
    if row is None:
        raise HTTPException(status_code=404, detail="self-grade not found")
    if not row.prompt_delta:
        raise HTTPException(status_code=400, detail="no prompt_delta to approve")
    row.approved_at = datetime.now(timezone.utc)
    row.approved_by = (user.email or "").lower()
    db.commit()
    return _serialize_grade(row)


@router.post("/self-grade/{grade_id}/reject")
def reject_prompt_delta(
    grade_id: int,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Owner rejects the proposal. Clears the delta so the UI stops
    nagging about it."""
    user = _require_user(request, db)
    if (user.email or "").lower() != OWNER_EMAIL:
        raise HTTPException(status_code=403, detail="Owner only")
    row = db.get(AISelfGrade, grade_id)
    if row is None:
        raise HTTPException(status_code=404, detail="self-grade not found")
    row.prompt_delta = None
    row.approved_at = None
    row.approved_by = (user.email or "").lower()
    db.commit()
    return _serialize_grade(row)


def _serialize_grade(r: AISelfGrade) -> dict[str, Any]:
    return {
        "id": r.id,
        "run_at": r.run_at.isoformat() if r.run_at else None,
        "window_days": r.window_days,
        "model": r.model,
        "artifacts_scored": r.artifacts_scored,
        "feedback_count": r.feedback_count,
        "precision_by_source": r.precision_by_source,
        "rejection_themes": r.rejection_themes,
        "overall_summary": r.overall_summary,
        "prompt_delta": r.prompt_delta,
        "approved_at": r.approved_at.isoformat() if r.approved_at else None,
        "approved_by": r.approved_by,
        "applied_at": r.applied_at.isoformat() if r.applied_at else None,
        "duration_ms": r.duration_ms,
    }
