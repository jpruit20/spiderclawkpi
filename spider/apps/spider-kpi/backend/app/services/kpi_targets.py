"""KPI targets service.

Operator-defined targets per metric, optionally bounded to a seasonal
window. The dashboard reads ``get_active_targets()`` to color tiles
and compute "% of target" deltas.

Resolution rule for ``get_active_target(metric_key, on_date)``:
  1. Pull every target for the metric.
  2. Keep rows whose [effective_start, effective_end) contains on_date
     (NULL bound = open-ended on that side).
  3. Among matches, prefer the narrowest window (most-specific wins
     over annual catch-all).
  4. Tiebreak by latest ``updated_at``.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import KpiTarget


def _window_width_days(t: KpiTarget) -> int:
    """A finite-window target wins over an open-ended one when both
    contain ``on_date``. Open-ended bounds count as 'very wide' so they
    sort last."""
    OPEN = 100_000
    s = t.effective_start
    e = t.effective_end
    if s is None and e is None:
        return OPEN
    if s is None or e is None:
        return OPEN // 2
    return max(1, (e - s).days)


def _contains(t: KpiTarget, on_date: date) -> bool:
    if t.effective_start is not None and on_date < t.effective_start:
        return False
    if t.effective_end is not None and on_date >= t.effective_end:
        return False
    return True


def get_active_target(db: Session, metric_key: str, *, on_date: Optional[date] = None) -> Optional[KpiTarget]:
    """Return the single active target for ``metric_key`` on ``on_date``
    (defaults to today). None if no row matches."""
    on_date = on_date or date.today()
    rows = db.execute(
        select(KpiTarget).where(KpiTarget.metric_key == metric_key)
    ).scalars().all()
    matches = [r for r in rows if _contains(r, on_date)]
    if not matches:
        return None
    # Sort: narrowest window first, then latest updated_at
    matches.sort(key=lambda t: (_window_width_days(t), -(t.updated_at.timestamp() if t.updated_at else 0)))
    return matches[0]


def get_active_targets(db: Session, *, on_date: Optional[date] = None) -> dict[str, dict[str, Any]]:
    """All active targets keyed by metric_key. Used by the trends
    endpoint to embed targets in the snapshot response."""
    on_date = on_date or date.today()
    rows = db.execute(select(KpiTarget)).scalars().all()
    by_metric: dict[str, list[KpiTarget]] = {}
    for r in rows:
        if _contains(r, on_date):
            by_metric.setdefault(r.metric_key, []).append(r)
    out: dict[str, dict[str, Any]] = {}
    for key, candidates in by_metric.items():
        candidates.sort(key=lambda t: (_window_width_days(t), -(t.updated_at.timestamp() if t.updated_at else 0)))
        winner = candidates[0]
        out[key] = _serialize(winner)
    return out


def list_targets(
    db: Session,
    *,
    metric_key: Optional[str] = None,
    division: Optional[str] = None,
    include_global: bool = True,
) -> list[dict[str, Any]]:
    q = select(KpiTarget)
    if metric_key:
        q = q.where(KpiTarget.metric_key == metric_key)
    if division is not None:
        if include_global:
            q = q.where((KpiTarget.division == division) | (KpiTarget.division.is_(None)))
        else:
            q = q.where(KpiTarget.division == division)
    q = q.order_by(KpiTarget.metric_key, KpiTarget.effective_start.asc().nulls_first())
    rows = db.execute(q).scalars().all()
    return [_serialize(r) for r in rows]


def upsert_target(
    db: Session,
    *,
    metric_key: str,
    target_value: float,
    direction: str = "min",
    effective_start: Optional[date] = None,
    effective_end: Optional[date] = None,
    season_label: Optional[str] = None,
    notes: Optional[str] = None,
    user: Optional[str] = None,
    division: Optional[str] = None,
    target_id: Optional[int] = None,
) -> KpiTarget:
    """Create a new target or update an existing one by id."""
    if target_id is not None:
        row = db.get(KpiTarget, target_id)
        if row is None:
            raise ValueError(f"kpi_target id={target_id} not found")
    else:
        row = KpiTarget(metric_key=metric_key, target_value=target_value)
        db.add(row)

    row.metric_key = metric_key
    row.target_value = target_value
    row.direction = direction if direction in ("min", "max") else "min"
    row.effective_start = effective_start
    row.effective_end = effective_end
    row.season_label = season_label
    row.notes = notes
    row.division = division
    row.owner_email = user or row.owner_email
    row.created_by = user or row.created_by
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


def delete_target(db: Session, *, target_id: int) -> bool:
    row = db.get(KpiTarget, target_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def _serialize(t: KpiTarget) -> dict[str, Any]:
    return {
        "id": t.id,
        "metric_key": t.metric_key,
        "target_value": float(t.target_value) if t.target_value is not None else None,
        "direction": t.direction,
        "effective_start": t.effective_start.isoformat() if t.effective_start else None,
        "effective_end": t.effective_end.isoformat() if t.effective_end else None,
        "season_label": t.season_label,
        "notes": t.notes,
        "division": t.division,
        "owner_email": t.owner_email,
        "created_by": t.created_by,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }
