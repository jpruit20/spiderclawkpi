from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import CXAction
from app.services.action_engine import ActionSignal, resolve_action, upsert_action_signal
from app.services.cx_snapshot import KPI_CONFIG, build_customer_experience_snapshot

settings = get_settings()


def ensure_cx_action_storage(db: Session) -> None:
    inspector = inspect(db.bind)
    if inspector.has_table('cx_actions'):
        return
    if settings.env == 'development' or settings.debug:
        raise RuntimeError('cx_actions table missing in development; apply Alembic migration 20260407_0005_cx_actions.py before running the app')
    raise RuntimeError('cx_actions table missing in production; apply Alembic migration 20260407_0005_cx_actions.py')


def _coerce_snapshot_timestamp(snapshot: dict[str, Any] | None) -> None:
    """The CX action evaluators are now called from the cache-first
    /api/cx/snapshot route, which passes a JSON-round-tripped payload.
    JSON has no datetime — `snapshot_timestamp` arrives as an ISO
    string. Coerce it back to datetime so _build_signal's
    `.isoformat()` call (and the ActionSignal model) keep working.

    Tolerant: leaves None alone, leaves real datetimes alone, parses
    Z-suffix and offset-aware ISO strings."""
    if snapshot is None:
        return
    ts = snapshot.get('snapshot_timestamp')
    if ts is None or isinstance(ts, datetime):
        return
    if isinstance(ts, str):
        try:
            # fromisoformat handles "+00:00" but not "Z" before py3.11.
            snapshot['snapshot_timestamp'] = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        except ValueError:
            snapshot['snapshot_timestamp'] = None


def _build_signal(metric: dict[str, Any], snapshot_timestamp: datetime, product_linked: bool) -> ActionSignal | None:
    if metric['status'] == 'green' or not metric.get('trigger_condition'):
        return None
    if not metric['critical_immediate'] and metric['consecutive_bad_days'] < 2:
        return None
    config = KPI_CONFIG[metric['key']]
    return ActionSignal(
        trigger_kpi=metric['key'],
        trigger_condition=metric['trigger_condition'],
        owner=config['owner'],
        co_owner='Kyle' if product_linked and metric['key'] in {'reopen_rate', 'escalation_rate', 'avg_close_time'} else None,
        escalation_owner='Joseph' if metric['status'] == 'red' and metric['consecutive_bad_days'] > 3 else None,
        title=config['title'],
        required_action=config['required_action'],
        priority='critical' if metric['critical_immediate'] else 'high' if metric['status'] == 'red' else 'medium',
        evidence=[
            {'metric': metric['key'], 'current': metric['current'], 'target': metric['target'], 'status': metric['status']},
            {'consecutive_bad_days': metric['consecutive_bad_days'], 'critical_immediate': metric['critical_immediate']},
            {'snapshot_timestamp': snapshot_timestamp.isoformat()},
        ],
        auto_close_rule={'type': 'kpi_recovery', 'requires_consecutive_green_days': 2, 'trigger_kpi': metric['key']},
        snapshot_timestamp=snapshot_timestamp,
    )


def evaluateCustomerExperienceActions(db: Session, snapshot: dict[str, Any] | None = None) -> list[CXAction]:
    ensure_cx_action_storage(db)
    snapshot = snapshot or build_customer_experience_snapshot(db)
    _coerce_snapshot_timestamp(snapshot)
    if snapshot.get('snapshot_timestamp') is None:
        return []
    grid_metrics = snapshot['grid_metrics']
    product_linked = bool(snapshot.get('product_linked'))
    actions: list[CXAction] = []
    for metric in grid_metrics:
        signal = _build_signal(metric, snapshot['snapshot_timestamp'], product_linked)
        if signal is None:
            continue
        action = upsert_action_signal(db, signal, reopen_predicate=lambda existing, _: True)
        actions.append(action)
    db.flush()
    return actions


def evaluateActionClosure(db: Session, snapshot: dict[str, Any] | None = None) -> list[CXAction]:
    ensure_cx_action_storage(db)
    snapshot = snapshot or build_customer_experience_snapshot(db)
    _coerce_snapshot_timestamp(snapshot)
    if snapshot.get('snapshot_timestamp') is None:
        return []
    metric_map = {metric['key']: metric for metric in snapshot['grid_metrics']}
    active = db.execute(select(CXAction).where(CXAction.status.in_(['open', 'in_progress']))).scalars().all()
    resolved: list[CXAction] = []
    for action in active:
        metric = metric_map.get(action.trigger_kpi)
        if metric and metric['consecutive_green_days'] >= 2:
            resolve_action(db, action, snapshot['snapshot_timestamp'])
            resolved.append(action)
    db.flush()
    return resolved


def seedCustomerExperienceActions(db: Session) -> list[CXAction]:
    ensure_cx_action_storage(db)
    snapshot = build_customer_experience_snapshot(db)
    if snapshot.get('snapshot_timestamp') is None:
        return []
    evaluateCustomerExperienceActions(db, snapshot)
    evaluateActionClosure(db, snapshot)
    db.commit()
    return db.execute(select(CXAction).order_by(CXAction.opened_at.desc())).scalars().all()


def update_cx_action_status(db: Session, action: CXAction, status: str) -> CXAction:
    action.status = status
    action.updated_at = datetime.now(timezone.utc)
    action.resolved_at = datetime.now(timezone.utc) if status == 'resolved' else None
    db.flush()
    return action
