from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.entities import ClarityPageMetric


def get_ux_friction_report(db: Session, limit: int = 20) -> list[dict]:
    """Return top pages ranked by friction_score, each with all metrics."""
    latest_date = db.execute(
        select(func.max(ClarityPageMetric.snapshot_date))
    ).scalar_one_or_none()
    if latest_date is None:
        return []

    rows = db.execute(
        select(ClarityPageMetric)
        .where(ClarityPageMetric.snapshot_date == latest_date)
        .order_by(desc(ClarityPageMetric.friction_score))
        .limit(limit)
    ).scalars().all()

    return [
        {
            "url": row.url,
            "page_path": row.page_path,
            "page_type": row.page_type,
            "sessions": row.sessions,
            "dead_clicks": row.dead_clicks,
            "dead_click_pct": row.dead_click_pct,
            "rage_clicks": row.rage_clicks,
            "rage_click_pct": row.rage_click_pct,
            "quick_backs": row.quick_backs,
            "quick_back_pct": row.quick_back_pct,
            "script_errors": row.script_errors,
            "script_error_pct": row.script_error_pct,
            "excessive_scroll": row.excessive_scroll,
            "friction_score": row.friction_score,
            "snapshot_date": row.snapshot_date.isoformat() if row.snapshot_date else None,
        }
        for row in rows
    ]


def get_page_type_summary(db: Session) -> list[dict]:
    """Return friction aggregated by page_type."""
    latest_date = db.execute(
        select(func.max(ClarityPageMetric.snapshot_date))
    ).scalar_one_or_none()
    if latest_date is None:
        return []

    rows = db.execute(
        select(
            ClarityPageMetric.page_type,
            func.count().label("page_count"),
            func.avg(ClarityPageMetric.friction_score).label("avg_friction"),
            func.max(ClarityPageMetric.friction_score).label("max_friction"),
            func.sum(ClarityPageMetric.sessions).label("total_sessions"),
            func.avg(ClarityPageMetric.dead_click_pct).label("avg_dead_click_pct"),
            func.avg(ClarityPageMetric.rage_click_pct).label("avg_rage_click_pct"),
            func.avg(ClarityPageMetric.quick_back_pct).label("avg_quick_back_pct"),
            func.avg(ClarityPageMetric.script_error_pct).label("avg_script_error_pct"),
        )
        .where(ClarityPageMetric.snapshot_date == latest_date)
        .group_by(ClarityPageMetric.page_type)
        .order_by(desc(func.avg(ClarityPageMetric.friction_score)))
    ).all()

    return [
        {
            "page_type": row.page_type,
            "page_count": row.page_count,
            "avg_friction": round(float(row.avg_friction or 0), 2),
            "max_friction": round(float(row.max_friction or 0), 2),
            "total_sessions": int(row.total_sessions or 0),
            "avg_dead_click_pct": round(float(row.avg_dead_click_pct or 0), 2),
            "avg_rage_click_pct": round(float(row.avg_rage_click_pct or 0), 2),
            "avg_quick_back_pct": round(float(row.avg_quick_back_pct or 0), 2),
            "avg_script_error_pct": round(float(row.avg_script_error_pct or 0), 2),
        }
        for row in rows
    ]


def get_product_page_health(db: Session) -> list[dict]:
    """Return metrics specifically for product pages."""
    latest_date = db.execute(
        select(func.max(ClarityPageMetric.snapshot_date))
    ).scalar_one_or_none()
    if latest_date is None:
        return []

    rows = db.execute(
        select(ClarityPageMetric)
        .where(
            ClarityPageMetric.snapshot_date == latest_date,
            ClarityPageMetric.page_type == "product",
        )
        .order_by(desc(ClarityPageMetric.friction_score))
    ).scalars().all()

    return [
        {
            "url": row.url,
            "page_path": row.page_path,
            "page_type": row.page_type,
            "sessions": row.sessions,
            "dead_clicks": row.dead_clicks,
            "dead_click_pct": row.dead_click_pct,
            "rage_clicks": row.rage_clicks,
            "rage_click_pct": row.rage_click_pct,
            "quick_backs": row.quick_backs,
            "quick_back_pct": row.quick_back_pct,
            "script_errors": row.script_errors,
            "script_error_pct": row.script_error_pct,
            "excessive_scroll": row.excessive_scroll,
            "friction_score": row.friction_score,
            "snapshot_date": row.snapshot_date.isoformat() if row.snapshot_date else None,
        }
        for row in rows
    ]
