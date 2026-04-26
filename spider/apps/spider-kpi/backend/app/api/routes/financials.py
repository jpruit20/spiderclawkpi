"""Financials API — gross profit + COGS table.

Single source of truth for COGS/gross-profit math. Every dashboard
page (Executive, Commercial, Marketing, Revenue Engine, Command
Center) reads from these endpoints so the same number shows up
everywhere.

COGS comes from ``services.product_cogs.get_canonical_cogs()`` which
reads ``sharepoint_product_intelligence.cogs_summary.canonical_total_usd``
— the AI-synthesized canonical figure that page owners can override
via the SharePoint intelligence card's source-of-truth picker.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.services.product_cogs import compute_gross_profit, get_canonical_cogs


router = APIRouter(prefix="/api/financials", tags=["financials"])


@router.get("/cogs-table")
def cogs_table(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Per-product canonical COGS, sourced from the SharePoint synthesis.
    Read by every page that needs to display unit COGS."""
    rows = get_canonical_cogs(db)
    return {
        "products": [
            {"product": p, **vals}
            for p, vals in rows.items()
        ],
    }


@router.get("/gross-profit")
def gross_profit(
    days: Optional[int] = Query(None, ge=1, le=730),
    start: Optional[str] = Query(None, description="YYYY-MM-DD inclusive"),
    end: Optional[str] = Query(None, description="YYYY-MM-DD exclusive"),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Cross-platform gross-profit. Returns revenue, units sold by
    product, applied COGS, gross profit, gross margin %.

    Default (no args) = lifetime. Pass ``days`` for trailing N days,
    or explicit ``start`` and ``end`` for a custom window.
    """
    from datetime import date as _date
    s = _date.fromisoformat(start) if start else None
    e = _date.fromisoformat(end) if end else None
    return compute_gross_profit(db, days=days, start=s, end=e)
