from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models import CXAction, FreshdeskAgentDaily, FreshdeskTicket, KPIDaily

KPI_OWNER = {
    'open_backlog': 'Jeremiah',
    'aged_tickets_24h': 'Jeremiah',
    'avg_close_time': 'Jeremiah',
    'reopen_rate': 'Jeremiah',
    'escalation_rate': 'Jeremiah',
    'queue_concentration_pct': 'Jeremiah',
}


def _normalize_date(value: datetime | None) -> str | None:
    return value.isoformat()[:10] if value else None


def _is_closed(status: str | None) -> bool:
    text = str(status or '').lower()
    return 'closed' in text or 'resolved' in text or 'solved' in text


def _consecutive_bad_days(rows: list[KPIDaily], selector, predicate) -> int:
    count = 0
    for row in reversed(rows):
        if predicate(selector(row)):
            count += 1
        else:
            break
    return count


def _compute_snapshot(db: Session) -> dict[str, Any] | None:
    rows = db.execute(select(KPIDaily).order_by(KPIDaily.business_date)).scalars().all()
    if not rows:
        return None
    snapshot = rows[-1]
    snapshot_ts = datetime.combine(snapshot.business_date, datetime.min.time(), tzinfo=timezone.utc)

    tickets = db.execute(select(FreshdeskTicket)).scalars().all()
    snapshot_date = str(snapshot.business_date)
    snapshot_open_tickets = []
    for ticket in tickets:
        created = _normalize_date(ticket.created_at_source)
        resolved = _normalize_date(ticket.resolved_at_source)
        if not created or created > snapshot_date:
            continue
        if resolved and resolved <= snapshot_date and _is_closed(ticket.status):
            continue
        snapshot_open_tickets.append(ticket)

    start7 = str(rows[max(0, len(rows) - 7)].business_date)
    assigned_counts: dict[str, int] = {}
    escalated = 0
    recent_tickets = 0
    product_linked_recent = 0
    for ticket in tickets:
        created = _normalize_date(ticket.created_at_source)
        if not created or created < start7 or created > snapshot_date:
            continue
        recent_tickets += 1
        agent = str(ticket.raw_payload.get('responder_name') if ticket.raw_payload else '' or ticket.agent_id or 'Unassigned')
        assigned_counts[agent] = assigned_counts.get(agent, 0) + 1
        text = f"{ticket.subject or ''} {ticket.category or ''} {' '.join(ticket.tags_json or [])}".lower()
        is_product = any(token in text for token in ['firmware', 'venom', 'disconnect', 'temperature', 'product'])
        if any(token in text for token in ['escalat', 'engineering', 'urgent']):
            escalated += 1
            if is_product:
                product_linked_recent += 1

    total_assigned = sum(assigned_counts.values())
    queue_concentration = (max(assigned_counts.values()) / total_assigned * 100) if total_assigned else 0.0
    escalation_rate = (escalated / recent_tickets * 100) if recent_tickets else 0.0
    aged_tickets = len(snapshot_open_tickets)
    product_linked = product_linked_recent > 0

    metrics = {
        'open_backlog': {'current': snapshot.open_backlog, 'target': 90, 'red': 140, 'critical': 180},
        'aged_tickets_24h': {'current': aged_tickets, 'target': 50, 'red': 90, 'critical': 120},
        'avg_close_time': {'current': snapshot.resolution_time, 'target': 24, 'red': 48, 'critical': 60},
        'reopen_rate': {'current': snapshot.reopen_rate, 'target': 5, 'red': 8, 'critical': 12},
        'escalation_rate': {'current': escalation_rate, 'target': 8, 'red': 12, 'critical': 18},
        'queue_concentration_pct': {'current': queue_concentration, 'target': 40, 'red': 50, 'critical': 60},
    }
    return {
        'snapshot_timestamp': snapshot_ts,
        'rows': rows,
        'metrics': metrics,
        'product_linked': product_linked,
    }


def _build_action(metric_key: str, data: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any] | None:
    current = float(data['current'])
    target = float(data['target'])
    red = float(data['red'])
    critical = float(data['critical'])
    status = 'green'
    trigger = None
    if current > red:
        status = 'red'
        trigger = f'{metric_key}_gt_{int(red)}'
    elif current > target:
        status = 'yellow'
        trigger = f'{metric_key}_gt_{int(target)}'
    if status == 'green':
        return None

    rows = snapshot['rows']
    selector_map = {
        'open_backlog': lambda r: r.open_backlog,
        'aged_tickets_24h': lambda r: r.open_backlog,
        'avg_close_time': lambda r: r.resolution_time,
        'reopen_rate': lambda r: r.reopen_rate,
        'escalation_rate': lambda r: r.reopen_rate,
        'queue_concentration_pct': lambda r: r.open_backlog,
    }
    consecutive = _consecutive_bad_days(rows, selector_map[metric_key], lambda v: float(v) > target)
    immediate = current > critical
    if not immediate and consecutive < 2:
        return None

    titles = {
        'open_backlog': 'Reduce active queue backlog',
        'aged_tickets_24h': 'Clear aged ticket queue',
        'avg_close_time': 'Reduce slow resolution cycle',
        'reopen_rate': 'Fix repeat-contact driver',
        'escalation_rate': 'Reduce escalation driver',
        'queue_concentration_pct': 'Rebalance assignment load',
    }
    required_map = {
        'open_backlog': 'Redistribute queue work immediately and clear the oldest backlog first.',
        'aged_tickets_24h': 'Assign same-day ownership on aged tickets and stop new tickets from aging into the bucket.',
        'avg_close_time': 'Review slow categories and rebalance work away from the slowest closure path.',
        'reopen_rate': 'Audit repeat-contact tickets and fix the underlying unresolved issue.',
        'escalation_rate': 'Identify escalation-heavy themes and remove the top escalation driver.',
        'queue_concentration_pct': 'Shift assignment away from the overloaded rep and rebalance queue ownership.',
    }
    priority = 'critical' if immediate else 'high' if status == 'red' else 'medium'
    co_owner = 'Kyle' if snapshot['product_linked'] and metric_key in {'reopen_rate', 'escalation_rate', 'avg_close_time'} else None
    escalation_owner = 'Joseph' if status == 'red' and consecutive > 3 else None
    return {
        'trigger_kpi': metric_key,
        'trigger_condition': trigger,
        'dedup_key': f'{metric_key}:{trigger}',
        'owner': KPI_OWNER[metric_key],
        'co_owner': co_owner,
        'escalation_owner': escalation_owner,
        'title': titles[metric_key],
        'required_action': required_map[metric_key],
        'priority': priority,
        'status': 'open',
        'evidence': [
            {'metric': metric_key, 'current': current, 'target': target},
            {'consecutive_bad_days': consecutive, 'critical_immediate': immediate},
        ],
        'auto_close_rule': {'type': 'kpi_recovery', 'requires_consecutive_green_days': 2, 'trigger_kpi': metric_key},
        'snapshot_timestamp': snapshot['snapshot_timestamp'],
        'consecutive_bad_days': consecutive,
    }


def evaluateCustomerExperienceActions(db: Session, snapshot: dict[str, Any] | None = None) -> list[CXAction]:
    snapshot = snapshot or _compute_snapshot(db)
    if snapshot is None:
        return []
    active_actions: list[CXAction] = []
    for metric_key, data in snapshot['metrics'].items():
        action_payload = _build_action(metric_key, data, snapshot)
        if action_payload is None:
            continue
        existing = db.execute(
            select(CXAction).where(
                CXAction.dedup_key == action_payload['dedup_key'],
                CXAction.status.in_(['open', 'in_progress'])
            ).limit(1)
        ).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if existing:
            existing.owner = action_payload['owner']
            existing.co_owner = action_payload['co_owner']
            existing.escalation_owner = action_payload['escalation_owner']
            existing.title = action_payload['title']
            existing.required_action = action_payload['required_action']
            existing.priority = action_payload['priority']
            existing.evidence = action_payload['evidence']
            existing.auto_close_rule = action_payload['auto_close_rule']
            existing.snapshot_timestamp = action_payload['snapshot_timestamp']
            existing.updated_at = now
            active_actions.append(existing)
        else:
            created = CXAction(
                trigger_kpi=action_payload['trigger_kpi'],
                trigger_condition=action_payload['trigger_condition'],
                dedup_key=action_payload['dedup_key'],
                owner=action_payload['owner'],
                co_owner=action_payload['co_owner'],
                escalation_owner=action_payload['escalation_owner'],
                title=action_payload['title'],
                required_action=action_payload['required_action'],
                priority=action_payload['priority'],
                status='open',
                evidence=action_payload['evidence'],
                opened_at=now,
                updated_at=now,
                auto_close_rule=action_payload['auto_close_rule'],
                snapshot_timestamp=action_payload['snapshot_timestamp'],
            )
            db.add(created)
            active_actions.append(created)
    db.flush()
    return active_actions


def evaluateActionClosure(db: Session, snapshot: dict[str, Any] | None = None) -> list[CXAction]:
    snapshot = snapshot or _compute_snapshot(db)
    if snapshot is None:
        return []
    rows = snapshot['rows']
    selector_map = {
        'open_backlog': lambda r: r.open_backlog <= 90,
        'aged_tickets_24h': lambda r: r.open_backlog <= 50,
        'avg_close_time': lambda r: r.resolution_time <= 24,
        'reopen_rate': lambda r: r.reopen_rate <= 5,
        'escalation_rate': lambda r: r.reopen_rate <= 5,
        'queue_concentration_pct': lambda r: r.open_backlog <= 90,
    }
    resolved: list[CXAction] = []
    active = db.execute(select(CXAction).where(CXAction.status.in_(['open', 'in_progress']))).scalars().all()
    now = datetime.now(timezone.utc)
    for action in active:
        last_two = rows[-2:] if len(rows) >= 2 else rows
        if len(last_two) >= 2 and all(selector_map[action.trigger_kpi](row) for row in last_two):
            action.status = 'resolved'
            action.resolved_at = now
            action.updated_at = now
            resolved.append(action)
    db.flush()
    return resolved


def seedCustomerExperienceActions(db: Session) -> list[CXAction]:
    snapshot = _compute_snapshot(db)
    if snapshot is None:
        return []
    evaluateCustomerExperienceActions(db, snapshot)
    evaluateActionClosure(db, snapshot)
    db.commit()
    return db.execute(select(CXAction).order_by(CXAction.opened_at.desc())).scalars().all()
