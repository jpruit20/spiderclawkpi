from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import CXAction


@dataclass
class ActionSignal:
    trigger_kpi: str
    trigger_condition: str
    owner: str
    co_owner: str | None
    escalation_owner: str | None
    title: str
    required_action: str
    priority: str
    evidence: list[dict[str, Any]]
    auto_close_rule: dict[str, Any]
    snapshot_timestamp: datetime

    @property
    def dedup_key(self) -> str:
        return f"{self.trigger_kpi}:{self.trigger_condition}"


ReopenPredicate = Callable[[CXAction, ActionSignal], bool]


def upsert_action_signal(db: Session, signal: ActionSignal, reopen_predicate: ReopenPredicate | None = None) -> CXAction:
    now = datetime.now(timezone.utc)
    existing = db.execute(
        select(CXAction)
        .where(CXAction.dedup_key == signal.dedup_key)
        .order_by(desc(CXAction.updated_at), desc(CXAction.opened_at))
        .limit(1)
    ).scalar_one_or_none()

    if existing is not None:
        existing.trigger_kpi = signal.trigger_kpi
        existing.trigger_condition = signal.trigger_condition
        existing.owner = signal.owner
        existing.co_owner = signal.co_owner
        existing.escalation_owner = signal.escalation_owner
        existing.title = signal.title
        existing.required_action = signal.required_action
        existing.priority = signal.priority
        existing.evidence = signal.evidence
        existing.auto_close_rule = signal.auto_close_rule
        existing.snapshot_timestamp = signal.snapshot_timestamp
        existing.updated_at = now
        if existing.status == 'resolved' and (reopen_predicate is None or reopen_predicate(existing, signal)):
            existing.status = 'open'
            existing.resolved_at = None
        db.flush()
        return existing

    created = CXAction(
        trigger_kpi=signal.trigger_kpi,
        trigger_condition=signal.trigger_condition,
        dedup_key=signal.dedup_key,
        owner=signal.owner,
        co_owner=signal.co_owner,
        escalation_owner=signal.escalation_owner,
        title=signal.title,
        required_action=signal.required_action,
        priority=signal.priority,
        status='open',
        evidence=signal.evidence,
        opened_at=now,
        auto_close_rule=signal.auto_close_rule,
        snapshot_timestamp=signal.snapshot_timestamp,
    )
    db.add(created)
    try:
        db.flush()
        return created
    except IntegrityError:
        db.rollback()
        existing = db.execute(
            select(CXAction)
            .where(CXAction.dedup_key == signal.dedup_key, CXAction.status.in_(['open', 'in_progress']))
            .order_by(desc(CXAction.updated_at), desc(CXAction.opened_at))
            .limit(1)
        ).scalar_one()
        existing.owner = signal.owner
        existing.co_owner = signal.co_owner
        existing.escalation_owner = signal.escalation_owner
        existing.title = signal.title
        existing.required_action = signal.required_action
        existing.priority = signal.priority
        existing.evidence = signal.evidence
        existing.auto_close_rule = signal.auto_close_rule
        existing.snapshot_timestamp = signal.snapshot_timestamp
        existing.updated_at = now
        db.flush()
        return existing


def resolve_action(db: Session, action: CXAction, snapshot_timestamp: datetime | None = None) -> CXAction:
    now = datetime.now(timezone.utc)
    action.status = 'resolved'
    action.resolved_at = now
    action.updated_at = now
    if snapshot_timestamp is not None:
        action.snapshot_timestamp = snapshot_timestamp
    db.flush()
    return action
