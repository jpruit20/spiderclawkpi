from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_dashboard_session
from app.services.personal_intelligence import build_daily_insights


router = APIRouter(prefix="/api/insights", tags=["personal-intelligence"], dependencies=[Depends(require_dashboard_session)])


@router.get("/daily")
def get_daily_insights(db: Session = Depends(db_session)):
    return build_daily_insights(db)
