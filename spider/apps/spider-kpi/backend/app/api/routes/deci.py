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
    DeciDomain,
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
    domain_id: Optional[int] = None
    cross_functional: bool = False
    due_date: Optional[str] = None  # ISO date string


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
    domain_id: Optional[int] = None
    cross_functional: Optional[bool] = None
    due_date: Optional[str] = None
    escalation_status: Optional[str] = None


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


class DomainCreate(BaseModel):
    name: str
    description: Optional[str] = None
    category: str = "operations"
    default_driver_id: Optional[int] = None
    default_executor_ids: list[int] = []
    default_contributor_ids: list[int] = []
    default_informed_ids: list[int] = []
    escalation_owner_id: Optional[int] = None
    escalation_threshold_days: int = 7
    sort_order: int = 0


class DomainUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    default_driver_id: Optional[int] = None
    default_executor_ids: Optional[list[int]] = None
    default_contributor_ids: Optional[list[int]] = None
    default_informed_ids: Optional[list[int]] = None
    escalation_owner_id: Optional[int] = None
    escalation_threshold_days: Optional[int] = None
    active: Optional[bool] = None
    sort_order: Optional[int] = None


class DomainOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    category: str
    default_driver_id: Optional[int] = None
    default_driver_name: Optional[str] = None
    default_executor_ids: list[int] = []
    default_contributor_ids: list[int] = []
    default_informed_ids: list[int] = []
    escalation_owner_id: Optional[int] = None
    escalation_owner_name: Optional[str] = None
    escalation_threshold_days: int = 7
    active: bool = True
    sort_order: int = 0
    decision_count: int = 0
    created_at: datetime
    updated_at: datetime

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
        "domain_id": decision.domain_id,
        "escalation_status": decision.escalation_status,
        "escalated_at": decision.escalated_at,
        "cross_functional": decision.cross_functional,
        "due_date": decision.due_date.isoformat() if decision.due_date else None,
        "resolved_at": decision.resolved_at,
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
# Decision Domains
# ---------------------------------------------------------------------------


@router.get("/domains")
def list_domains(db: Session = Depends(db_session)):
    domains = db.execute(
        select(DeciDomain).order_by(DeciDomain.sort_order, DeciDomain.name)
    ).scalars().all()
    member_names = _member_name_map(db)

    # Count decisions per domain
    domain_decision_counts = {}
    count_rows = db.execute(
        select(DeciDecision.domain_id, func.count().label("cnt"))
        .where(DeciDecision.domain_id.is_not(None))
        .group_by(DeciDecision.domain_id)
    ).all()
    for row in count_rows:
        domain_decision_counts[row[0]] = row[1]

    return [
        {
            "id": d.id,
            "name": d.name,
            "description": d.description,
            "category": d.category,
            "default_driver_id": d.default_driver_id,
            "default_driver_name": member_names.get(d.default_driver_id) if d.default_driver_id else None,
            "default_executor_ids": d.default_executor_ids or [],
            "default_contributor_ids": d.default_contributor_ids or [],
            "default_informed_ids": d.default_informed_ids or [],
            "escalation_owner_id": d.escalation_owner_id,
            "escalation_owner_name": member_names.get(d.escalation_owner_id) if d.escalation_owner_id else None,
            "escalation_threshold_days": d.escalation_threshold_days,
            "active": d.active,
            "sort_order": d.sort_order,
            "decision_count": domain_decision_counts.get(d.id, 0),
            "created_at": d.created_at,
            "updated_at": d.updated_at,
        }
        for d in domains
    ]


@router.post("/domains", status_code=201)
def create_domain(body: DomainCreate, db: Session = Depends(db_session)):
    domain = DeciDomain(
        name=body.name,
        description=body.description,
        category=body.category,
        default_driver_id=body.default_driver_id,
        default_executor_ids=body.default_executor_ids,
        default_contributor_ids=body.default_contributor_ids,
        default_informed_ids=body.default_informed_ids,
        escalation_owner_id=body.escalation_owner_id,
        escalation_threshold_days=body.escalation_threshold_days,
        sort_order=body.sort_order,
    )
    db.add(domain)
    db.commit()
    db.refresh(domain)
    member_names = _member_name_map(db)
    return {
        "id": domain.id,
        "name": domain.name,
        "description": domain.description,
        "category": domain.category,
        "default_driver_id": domain.default_driver_id,
        "default_driver_name": member_names.get(domain.default_driver_id) if domain.default_driver_id else None,
        "default_executor_ids": domain.default_executor_ids or [],
        "default_contributor_ids": domain.default_contributor_ids or [],
        "default_informed_ids": domain.default_informed_ids or [],
        "escalation_owner_id": domain.escalation_owner_id,
        "escalation_owner_name": member_names.get(domain.escalation_owner_id) if domain.escalation_owner_id else None,
        "escalation_threshold_days": domain.escalation_threshold_days,
        "active": domain.active,
        "sort_order": domain.sort_order,
        "decision_count": 0,
        "created_at": domain.created_at,
        "updated_at": domain.updated_at,
    }


@router.put("/domains/{domain_id}")
def update_domain(domain_id: int, body: DomainUpdate, db: Session = Depends(db_session)):
    domain = db.execute(
        select(DeciDomain).where(DeciDomain.id == domain_id)
    ).scalar_one_or_none()
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(domain, field, value)
    db.commit()
    db.refresh(domain)
    member_names = _member_name_map(db)
    decision_count = db.execute(
        select(func.count()).select_from(DeciDecision).where(DeciDecision.domain_id == domain_id)
    ).scalar_one()
    return {
        "id": domain.id,
        "name": domain.name,
        "description": domain.description,
        "category": domain.category,
        "default_driver_id": domain.default_driver_id,
        "default_driver_name": member_names.get(domain.default_driver_id) if domain.default_driver_id else None,
        "default_executor_ids": domain.default_executor_ids or [],
        "default_contributor_ids": domain.default_contributor_ids or [],
        "default_informed_ids": domain.default_informed_ids or [],
        "escalation_owner_id": domain.escalation_owner_id,
        "escalation_owner_name": member_names.get(domain.escalation_owner_id) if domain.escalation_owner_id else None,
        "escalation_threshold_days": domain.escalation_threshold_days,
        "active": domain.active,
        "sort_order": domain.sort_order,
        "decision_count": decision_count,
        "created_at": domain.created_at,
        "updated_at": domain.updated_at,
    }


@router.post("/domains/seed", status_code=201)
def seed_domains(db: Session = Depends(db_session)):
    """Seed the 12 initial decision domains if they don't exist."""
    INITIAL_DOMAINS = [
        {"name": "New Product Concept Direction", "category": "product", "description": "Go/no-go decisions on new product ideas, market fit analysis, and concept validation", "sort_order": 1},
        {"name": "Product Improvements & Iterations", "category": "product", "description": "Feature enhancements, design refinements, and iterative improvements to existing products", "sort_order": 2},
        {"name": "Production Readiness & Launch", "category": "manufacturing", "description": "Manufacturing readiness, tooling decisions, supplier selection, and launch timing", "sort_order": 3},
        {"name": "Quality & Warranty Standards", "category": "manufacturing", "description": "Quality control thresholds, warranty policy changes, and defect resolution protocols", "sort_order": 4},
        {"name": "Pricing & Revenue Strategy", "category": "commercial", "description": "Pricing changes, discount structures, bundle strategies, and revenue optimization", "sort_order": 5},
        {"name": "Marketing & Brand Positioning", "category": "commercial", "description": "Campaign decisions, channel strategy, brand messaging, and market positioning", "sort_order": 6},
        {"name": "Customer Experience & Support", "category": "cx", "description": "Support process changes, SLA adjustments, customer journey improvements", "sort_order": 7},
        {"name": "Technology & Infrastructure", "category": "engineering", "description": "Tech stack decisions, infrastructure investments, firmware architecture", "sort_order": 8},
        {"name": "Supply Chain & Logistics", "category": "operations", "description": "Supplier changes, inventory strategy, shipping and fulfillment decisions", "sort_order": 9},
        {"name": "Partnership & Channel Strategy", "category": "commercial", "description": "Retail partnerships, distribution agreements, co-marketing deals", "sort_order": 10},
        {"name": "Regulatory & Compliance", "category": "operations", "description": "Safety certifications, regulatory compliance, legal requirements", "sort_order": 11},
        {"name": "Team & Organizational", "category": "operations", "description": "Hiring decisions, role changes, organizational structure, vendor relationships", "sort_order": 12},
    ]

    existing = {d.name for d in db.execute(select(DeciDomain)).scalars().all()}
    created = []
    for domain_data in INITIAL_DOMAINS:
        if domain_data["name"] not in existing:
            domain = DeciDomain(**domain_data)
            db.add(domain)
            created.append(domain_data["name"])

    db.commit()
    return {"seeded": len(created), "domains": created}


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
    if body.domain_id:
        decision.domain_id = body.domain_id
    decision.cross_functional = body.cross_functional
    if body.due_date:
        from datetime import date as date_type
        decision.due_date = date_type.fromisoformat(body.due_date)
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
    skip_fields = assignment_fields | {"due_date"}
    for field, value in update_data.items():
        if field in skip_fields:
            continue
        setattr(decision, field, value)

    # Parse due_date if provided
    if "due_date" in update_data:
        if update_data["due_date"] is not None:
            from datetime import date as date_type
            decision.due_date = date_type.fromisoformat(update_data["due_date"])
        else:
            decision.due_date = None

    # Set resolved_at when status changes to "complete"
    if "status" in update_data and update_data["status"] == "complete" and decision.resolved_at is None:
        decision.resolved_at = datetime.now(timezone.utc)

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

    # ---- Domain Stats ----
    domains = db.execute(
        select(DeciDomain).where(DeciDomain.active.is_(True)).order_by(DeciDomain.sort_order)
    ).scalars().all()

    domain_decision_counts: dict[int, int] = {}
    domain_active_counts: dict[int, int] = {}
    count_rows = db.execute(
        select(DeciDecision.domain_id, func.count().label("cnt"))
        .where(DeciDecision.domain_id.is_not(None))
        .group_by(DeciDecision.domain_id)
    ).all()
    for row in count_rows:
        domain_decision_counts[row[0]] = row[1]

    active_rows = db.execute(
        select(DeciDecision.domain_id, func.count().label("cnt"))
        .where(
            DeciDecision.domain_id.is_not(None),
            DeciDecision.status.in_(["not_started", "in_progress", "blocked"]),
        )
        .group_by(DeciDecision.domain_id)
    ).all()
    for row in active_rows:
        domain_active_counts[row[0]] = row[1]

    domain_stats = [
        {
            "id": d.id,
            "name": d.name,
            "category": d.category,
            "total_decisions": domain_decision_counts.get(d.id, 0),
            "active_decisions": domain_active_counts.get(d.id, 0),
            "default_driver_name": member_names.get(d.default_driver_id) if d.default_driver_id else None,
            "escalation_owner_name": member_names.get(d.escalation_owner_id) if d.escalation_owner_id else None,
        }
        for d in domains
    ]

    # ---- Escalation Check ----
    # Auto-detect decisions that should be escalated
    escalation_warnings = []
    non_complete = db.execute(
        select(DeciDecision).where(DeciDecision.status != "complete")
    ).scalars().all()

    for d in non_complete:
        if d.domain_id:
            domain = next((dom for dom in domains if dom.id == d.domain_id), None)
            if domain:
                days_since_update = (now - d.updated_at).total_seconds() / 86400 if d.updated_at else 999
                if days_since_update > domain.escalation_threshold_days and d.escalation_status != "escalated":
                    escalation_warnings.append({
                        "id": d.id,
                        "title": d.title,
                        "domain": domain.name,
                        "days_stale": round(days_since_update),
                        "threshold_days": domain.escalation_threshold_days,
                        "escalation_owner": member_names.get(domain.escalation_owner_id) if domain.escalation_owner_id else None,
                    })

    return {
        "bottlenecks": bottlenecks,
        "ownership_map": ownership_map,
        "critical_feed": critical_feed,
        "velocity": velocity,
        "domain_stats": domain_stats,
        "escalation_warnings": escalation_warnings,
    }
