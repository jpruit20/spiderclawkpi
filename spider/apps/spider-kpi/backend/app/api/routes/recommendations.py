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
