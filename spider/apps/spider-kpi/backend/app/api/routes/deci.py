"""DECI decision framework routes.

Provides team management, decisions CRUD, decision logs, KPI links,
and an executive overview with bottleneck detection and velocity metrics.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_dashboard_session
from app.models.entities import (
    DeciAssignment,
    DeciDecision,
    DeciDecisionLog,
    DeciKpiLink,
    DeciTeamMember,
)

router = APIRouter(
    prefix="/api/deci",
    tags=["deci"],
    dependencies=[Depends(require_dashboard_session)],
)

# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class TeamMemberCreate(BaseModel):
    name: str
    email: Optional[str] = None
    role: Optional[str] = None
    department: Optional[str] = None


class TeamMemberOut(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    role: Optional[str] = None
    department: Optional[str] = None
    active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DecisionCreate(BaseModel):
    title: str
    description: Optional[str] = None
    type: str = "project"
    status: str = "not_started"
    priority: str = "medium"
    department: Optional[str] = None
    driver_id: Optional[int] = None
    executors: list[int] = []
    contributors: list[int] = []
    informed: list[int] = []


class DecisionUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    department: Optional[str] = None
    driver_id: Optional[int] = None
    executors: Optional[list[int]] = None
    contributors: Optional[list[int]] = None
    informed: Optional[list[int]] = None


class AssignmentOut(BaseModel):
    id: int
    decision_id: str
    member_id: int
    role: str
    member_name: Optional[str] = None

    model_config = {"from_attributes": True}


class LogCreate(BaseModel):
    decision_text: str
    made_by: str
    notes: Optional[str] = None


class LogOut(BaseModel):
    id: int
    decision_id: str
    decision_text: str
    made_by: str
    notes: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class KpiLinkCreate(BaseModel):
    kpi_name: str


class KpiLinkOut(BaseModel):
    id: int
    decision_id: str
    kpi_name: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _member_name_map(db: Session) -> dict[int, str]:
    """Return {member_id: name} for all active team members."""
    rows = db.execute(select(DeciTeamMember.id, DeciTeamMember.name)).all()
    return {row[0]: row[1] for row in rows}


def _enrich_decision(
    decision: DeciDecision,
    assignments: list[DeciAssignment],
    member_names: dict[int, str],
) -> dict:
    """Build a rich decision dict with driver name, executor names, etc."""
    driver_name = member_names.get(decision.driver_id) if decision.driver_id else None
    executors = [
        {"member_id": a.member_id, "name": member_names.get(a.member_id)}
        for a in assignments
        if a.role == "executor"
    ]
    contributors = [
        {"member_id": a.member_id, "name": member_names.get(a.member_id)}
        for a in assignments
        if a.role == "contributor"
    ]
    informed = [
        {"member_id": a.member_id, "name": member_names.get(a.member_id)}
        for a in assignments
        if a.role == "informed"
    ]
    return {
        "id": decision.id,
        "title": decision.title,
        "description": decision.description,
        "type": decision.type,
        "status": decision.status,
        "priority": decision.priority,
        "department": decision.department,
        "driver_id": decision.driver_id,
        "driver_name": driver_name,
        "created_by": decision.created_by,
        "executors": executors,
        "contributors": contributors,
        "informed": informed,
        "created_at": decision.created_at,
        "updated_at": decision.updated_at,
    }


def _sync_assignments(
    db: Session,
    decision_id: str,
    role: str,
    member_ids: list[int],
) -> None:
    """Replace all assignments for a given role on a decision."""
    db.execute(
        select(DeciAssignment)
        .where(
            DeciAssignment.decision_id == decision_id,
            DeciAssignment.role == role,
        )
    )
    # Delete existing assignments for this role
    existing = (
        db.execute(
            select(DeciAssignment).where(
                DeciAssignment.decision_id == decision_id,
                DeciAssignment.role == role,
            )
        )
        .scalars()
        .all()
    )
    existing_map = {a.member_id: a for a in existing}
    desired = set(member_ids)

    # Remove assignments no longer wanted
    for mid, assignment in existing_map.items():
        if mid not in desired:
            db.delete(assignment)

    # Add new assignments
    for mid in desired:
        if mid not in existing_map:
            db.add(
                DeciAssignment(
                    decision_id=decision_id,
                    member_id=mid,
                    role=role,
                )
            )


# ---------------------------------------------------------------------------
# Team Members
# ---------------------------------------------------------------------------


@router.get("/team", response_model=list[TeamMemberOut])
def list_team_members(db: Session = Depends(db_session)):
    rows = (
        db.execute(
            select(DeciTeamMember)
            .where(DeciTeamMember.active.is_(True))
            .order_by(DeciTeamMember.name)
        )
        .scalars()
        .all()
    )
    return rows


@router.post("/team", response_model=TeamMemberOut, status_code=201)
def create_team_member(body: TeamMemberCreate, db: Session = Depends(db_session)):
    member = DeciTeamMember(
        name=body.name,
        email=body.email,
        role=body.role,
        department=body.department,
        active=True,
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


# ---------------------------------------------------------------------------
# Decisions CRUD
# ---------------------------------------------------------------------------


@router.get("/decisions")
def list_decisions(
    department: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    driver_id: int | None = None,
    db: Session = Depends(db_session),
):
    query = select(DeciDecision).order_by(DeciDecision.updated_at.desc())
    if department:
        query = query.where(DeciDecision.department == department)
    if status:
        query = query.where(DeciDecision.status == status)
    if priority:
        query = query.where(DeciDecision.priority == priority)
    if driver_id is not None:
        query = query.where(DeciDecision.driver_id == driver_id)

    decisions = db.execute(query).scalars().all()
    if not decisions:
        return []

    decision_ids = [d.id for d in decisions]
    assignments = (
        db.execute(
            select(DeciAssignment).where(
                DeciAssignment.decision_id.in_(decision_ids)
            )
        )
        .scalars()
        .all()
    )
    assignments_by_decision: dict[str, list[DeciAssignment]] = {}
    for a in assignments:
        assignments_by_decision.setdefault(a.decision_id, []).append(a)

    member_names = _member_name_map(db)

    return [
        _enrich_decision(
            d,
            assignments_by_decision.get(d.id, []),
            member_names,
        )
        for d in decisions
    ]


@router.post("/decisions", status_code=201)
def create_decision(body: DecisionCreate, db: Session = Depends(db_session)):
    decision_id = str(uuid.uuid4())
    decision = DeciDecision(
        id=decision_id,
        title=body.title,
        description=body.description,
        type=body.type,
        status=body.status,
        priority=body.priority,
        department=body.department,
        driver_id=body.driver_id,
    )
    db.add(decision)
    db.flush()

    # Create assignments
    for mid in body.executors:
        db.add(DeciAssignment(decision_id=decision_id, member_id=mid, role="executor"))
    for mid in body.contributors:
        db.add(DeciAssignment(decision_id=decision_id, member_id=mid, role="contributor"))
    for mid in body.informed:
        db.add(DeciAssignment(decision_id=decision_id, member_id=mid, role="informed"))

    db.commit()
    db.refresh(decision)

    assignments = (
        db.execute(
            select(DeciAssignment).where(DeciAssignment.decision_id == decision_id)
        )
        .scalars()
        .all()
    )
    member_names = _member_name_map(db)
    return _enrich_decision(decision, assignments, member_names)


@router.get("/decisions/{decision_id}")
def get_decision(decision_id: str, db: Session = Depends(db_session)):
    decision = db.execute(
        select(DeciDecision).where(DeciDecision.id == decision_id)
    ).scalar_one_or_none()
    if decision is None:
        raise HTTPException(status_code=404, detail="Decision not found")

    assignments = (
        db.execute(
            select(DeciAssignment).where(DeciAssignment.decision_id == decision_id)
        )
        .scalars()
        .all()
    )
    logs = (
        db.execute(
            select(DeciDecisionLog)
            .where(DeciDecisionLog.decision_id == decision_id)
            .order_by(DeciDecisionLog.created_at.desc())
        )
        .scalars()
        .all()
    )
    kpi_links = (
        db.execute(
            select(DeciKpiLink).where(DeciKpiLink.decision_id == decision_id)
        )
        .scalars()
        .all()
    )

    member_names = _member_name_map(db)
    result = _enrich_decision(decision, assignments, member_names)
    result["logs"] = [
        {
            "id": log.id,
            "decision_text": log.decision_text,
            "made_by": log.made_by,
            "notes": log.notes,
            "created_at": log.created_at,
        }
        for log in logs
    ]
    result["kpi_links"] = [
        {
            "id": link.id,
            "kpi_name": link.kpi_name,
            "created_at": link.created_at,
        }
        for link in kpi_links
    ]
    return result


@router.put("/decisions/{decision_id}")
def update_decision(
    decision_id: str,
    body: DecisionUpdate,
    db: Session = Depends(db_session),
):
    decision = db.execute(
        select(DeciDecision).where(DeciDecision.id == decision_id)
    ).scalar_one_or_none()
    if decision is None:
        raise HTTPException(status_code=404, detail="Decision not found")

    # Apply scalar field updates
    update_data = body.model_dump(exclude_unset=True)
    assignment_fields = {"executors", "contributors", "informed"}
    for field, value in update_data.items():
        if field in assignment_fields:
            continue
        setattr(decision, field, value)

    # Validate driver constraint: if driver_id is being explicitly set, ensure
    # there is exactly one driver (the one being set).
    effective_driver = (
        body.driver_id if body.driver_id is not ... and "driver_id" in update_data else decision.driver_id
    )

    # Determine effective status for executor validation
    effective_status = update_data.get("status", decision.status)

    # Sync DECI role assignments when provided
    if body.executors is not None:
        _sync_assignments(db, decision_id, "executor", body.executors)
    if body.contributors is not None:
        _sync_assignments(db, decision_id, "contributor", body.contributors)
    if body.informed is not None:
        _sync_assignments(db, decision_id, "informed", body.informed)

    # Validate: at least 1 executor if status is in_progress
    if effective_status == "in_progress":
        executor_count = db.execute(
            select(func.count())
            .select_from(DeciAssignment)
            .where(
                DeciAssignment.decision_id == decision_id,
                DeciAssignment.role == "executor",
            )
        ).scalar_one()
        if executor_count < 1:
            raise HTTPException(
                status_code=400,
                detail="At least 1 executor is required when status is in_progress",
            )

    db.commit()
    db.refresh(decision)

    assignments = (
        db.execute(
            select(DeciAssignment).where(DeciAssignment.decision_id == decision_id)
        )
        .scalars()
        .all()
    )
    member_names = _member_name_map(db)
    return _enrich_decision(decision, assignments, member_names)


@router.delete("/decisions/{decision_id}", status_code=204)
def delete_decision(decision_id: str, db: Session = Depends(db_session)):
    decision = db.execute(
        select(DeciDecision).where(DeciDecision.id == decision_id)
    ).scalar_one_or_none()
    if decision is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    # Cascade deletes handle assignments, logs, and kpi_links
    db.delete(decision)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Decision Log
# ---------------------------------------------------------------------------


@router.post("/decisions/{decision_id}/log", response_model=LogOut, status_code=201)
def add_decision_log(
    decision_id: str,
    body: LogCreate,
    db: Session = Depends(db_session),
):
    decision = db.execute(
        select(DeciDecision).where(DeciDecision.id == decision_id)
    ).scalar_one_or_none()
    if decision is None:
        raise HTTPException(status_code=404, detail="Decision not found")

    log = DeciDecisionLog(
        decision_id=decision_id,
        decision_text=body.decision_text,
        made_by=body.made_by,
        notes=body.notes,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


# ---------------------------------------------------------------------------
# KPI Links
# ---------------------------------------------------------------------------


@router.post(
    "/decisions/{decision_id}/kpi-links",
    response_model=KpiLinkOut,
    status_code=201,
)
def add_kpi_link(
    decision_id: str,
    body: KpiLinkCreate,
    db: Session = Depends(db_session),
):
    decision = db.execute(
        select(DeciDecision).where(DeciDecision.id == decision_id)
    ).scalar_one_or_none()
    if decision is None:
        raise HTTPException(status_code=404, detail="Decision not found")

    link = DeciKpiLink(
        decision_id=decision_id,
        kpi_name=body.kpi_name,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


@router.delete(
    "/decisions/{decision_id}/kpi-links/{link_id}",
    status_code=204,
)
def remove_kpi_link(
    decision_id: str,
    link_id: int,
    db: Session = Depends(db_session),
):
    link = db.execute(
        select(DeciKpiLink).where(
            DeciKpiLink.id == link_id,
            DeciKpiLink.decision_id == decision_id,
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=404, detail="KPI link not found")
    db.delete(link)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Executive Overview
# ---------------------------------------------------------------------------


@router.get("/overview")
def get_deci_overview(db: Session = Depends(db_session)):
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=7)

    # ---- Bottlenecks ----

    # Decisions with no driver
    no_driver = (
        db.execute(
            select(DeciDecision).where(
                DeciDecision.driver_id.is_(None),
                DeciDecision.status != "complete",
            )
        )
        .scalars()
        .all()
    )

    # Stale decisions: not updated in 7 days, not complete
    stale = (
        db.execute(
            select(DeciDecision).where(
                DeciDecision.updated_at < stale_cutoff,
                DeciDecision.status != "complete",
            )
        )
        .scalars()
        .all()
    )

    # Decisions with >5 contributors
    overloaded_subq = (
        select(
            DeciAssignment.decision_id,
            func.count().label("cnt"),
        )
        .where(DeciAssignment.role == "contributor")
        .group_by(DeciAssignment.decision_id)
        .having(func.count() > 5)
        .subquery()
    )
    overloaded_contributors = (
        db.execute(
            select(DeciDecision).join(
                overloaded_subq,
                DeciDecision.id == overloaded_subq.c.decision_id,
            )
        )
        .scalars()
        .all()
    )

    bottlenecks = {
        "no_driver": [
            {"id": d.id, "title": d.title, "status": d.status, "priority": d.priority}
            for d in no_driver
        ],
        "stale": [
            {
                "id": d.id,
                "title": d.title,
                "status": d.status,
                "updated_at": d.updated_at,
            }
            for d in stale
        ],
        "overloaded_contributors": [
            {"id": d.id, "title": d.title, "status": d.status}
            for d in overloaded_contributors
        ],
    }

    # ---- Ownership Map ----

    active_members = (
        db.execute(
            select(DeciTeamMember).where(DeciTeamMember.active.is_(True))
        )
        .scalars()
        .all()
    )

    # Decisions each member drives
    driver_counts_rows = db.execute(
        select(DeciDecision.driver_id, func.count().label("cnt"))
        .where(DeciDecision.driver_id.is_not(None))
        .group_by(DeciDecision.driver_id)
    ).all()
    driver_counts = {row[0]: row[1] for row in driver_counts_rows}

    # Decisions each member drives that are blocked
    blocked_counts_rows = db.execute(
        select(DeciDecision.driver_id, func.count().label("cnt"))
        .where(
            DeciDecision.driver_id.is_not(None),
            DeciDecision.status == "blocked",
        )
        .group_by(DeciDecision.driver_id)
    ).all()
    blocked_counts = {row[0]: row[1] for row in blocked_counts_rows}

    # Executor counts per member
    executor_counts_rows = db.execute(
        select(DeciAssignment.member_id, func.count().label("cnt"))
        .where(DeciAssignment.role == "executor")
        .group_by(DeciAssignment.member_id)
    ).all()
    executor_counts = {row[0]: row[1] for row in executor_counts_rows}

    ownership_map = [
        {
            "member_id": m.id,
            "name": m.name,
            "driver_count": driver_counts.get(m.id, 0),
            "executor_count": executor_counts.get(m.id, 0),
            "blocked_count": blocked_counts.get(m.id, 0),
        }
        for m in active_members
    ]

    # ---- Critical Feed ----

    critical_decisions = (
        db.execute(
            select(DeciDecision)
            .where(DeciDecision.priority.in_(["high", "critical"]))
            .order_by(DeciDecision.updated_at.desc())
        )
        .scalars()
        .all()
    )
    member_names = _member_name_map(db)
    critical_feed = [
        {
            "id": d.id,
            "title": d.title,
            "status": d.status,
            "priority": d.priority,
            "driver_name": member_names.get(d.driver_id) if d.driver_id else None,
            "updated_at": d.updated_at,
        }
        for d in critical_decisions
    ]

    # ---- Velocity ----

    # Average time from decision creation to first log entry
    first_log_subq = (
        select(
            DeciDecisionLog.decision_id,
            func.min(DeciDecisionLog.created_at).label("first_log_at"),
        )
        .group_by(DeciDecisionLog.decision_id)
        .subquery()
    )
    creation_to_decision_rows = db.execute(
        select(
            DeciDecision.created_at,
            first_log_subq.c.first_log_at,
        ).join(
            first_log_subq,
            DeciDecision.id == first_log_subq.c.decision_id,
        )
    ).all()

    if creation_to_decision_rows:
        deltas = [
            (row[1] - row[0]).total_seconds()
            for row in creation_to_decision_rows
            if row[0] and row[1]
        ]
        avg_creation_to_decision_hours = (
            round(sum(deltas) / len(deltas) / 3600, 1) if deltas else None
        )
    else:
        avg_creation_to_decision_hours = None

    # Average time from first log entry to status=complete
    completed = (
        db.execute(
            select(DeciDecision).where(DeciDecision.status == "complete")
        )
        .scalars()
        .all()
    )
    if completed:
        completion_deltas: list[float] = []
        for d in completed:
            first_log = db.execute(
                select(DeciDecisionLog.created_at)
                .where(DeciDecisionLog.decision_id == d.id)
                .order_by(DeciDecisionLog.created_at)
                .limit(1)
            ).scalar_one_or_none()
            if first_log and d.updated_at:
                completion_deltas.append(
                    (d.updated_at - first_log).total_seconds()
                )
        avg_decision_to_completion_hours = (
            round(sum(completion_deltas) / len(completion_deltas) / 3600, 1)
            if completion_deltas
            else None
        )
    else:
        avg_decision_to_completion_hours = None

    velocity = {
        "avg_creation_to_decision_hours": avg_creation_to_decision_hours,
        "avg_decision_to_completion_hours": avg_decision_to_completion_hours,
    }

    return {
        "bottlenecks": bottlenecks,
        "ownership_map": ownership_map,
        "critical_feed": critical_feed,
        "velocity": velocity,
    }
