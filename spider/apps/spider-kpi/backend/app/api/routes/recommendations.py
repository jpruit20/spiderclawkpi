"""Action Recommendations API.

Surfaces "do this next" items per division (see services/
recommendations.py for the engine and individual generators).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.services.recommendations import recommendations_for


router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


VALID_DIVISIONS = {"pe", "cx", "marketing", "operations", "firmware"}


@router.get("/all/morning-brief")
def all_divisions_morning_brief(
    max_per_division: int = 3,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """One-glance morning briefing across every division.

    Powers the CommandCenter's "what's hot this morning" card.
    Severity sorted within each division, then divisions ranked by
    whichever has the highest-severity top item so the most urgent
    bucket renders at the top.
    """
    blocks: list[dict[str, Any]] = []
    severity_rank = {"critical": 0, "warn": 1, "info": 2}
    for div in sorted(VALID_DIVISIONS):
        items = recommendations_for(db, div)
        if not items:
            continue
        blocks.append({
            "division": div,
            "top_severity": items[0].get("severity"),
            "items": items[:max_per_division],
            "total": len(items),
        })
    blocks.sort(key=lambda b: severity_rank.get(b.get("top_severity") or "info", 99))

    flat: list[dict[str, Any]] = []
    for b in blocks:
        for item in b["items"]:
            flat.append({**item, "division": b["division"]})

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_actions": sum(b["total"] for b in blocks),
        "shown": len(flat),
        "by_division": blocks,
        "flat": flat,
    }


@router.get("/{division}")
def get_recommendations(
    division: str,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    if division not in VALID_DIVISIONS:
        raise HTTPException(status_code=400, detail=f"Unknown division. Valid: {sorted(VALID_DIVISIONS)}")
    items = recommendations_for(db, division)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "division": division,
        "count": len(items),
        "by_severity": {
            "critical": sum(1 for r in items if r.get("severity") == "critical"),
            "warn": sum(1 for r in items if r.get("severity") == "warn"),
            "info": sum(1 for r in items if r.get("severity") == "info"),
        },
        "recommendations": items,
    }
