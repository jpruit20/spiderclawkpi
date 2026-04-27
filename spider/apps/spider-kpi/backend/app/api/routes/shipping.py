"""Shipping intelligence + CX-correlation API.

Operations and CX pages read from these endpoints to render shipping
KPIs (carrier mix, transit, geographic distribution, 3PL ROI) and the
WISMO ticket correlation card.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.services.shipping_intelligence import (
    carrier_mix,
    geographic_distribution,
    shipping_cost_trend,
    threepl_roi_estimator,
)
from app.services.cx_shipping_correlation import cx_shipping_summary


router = APIRouter(prefix="/api/shipping", tags=["shipping"])


@router.get("/carrier-mix")
def get_carrier_mix(days: Optional[int] = Query(90, ge=1, le=730), db: Session = Depends(db_session)) -> dict[str, Any]:
    return carrier_mix(db, days=days)


@router.get("/geographic-distribution")
def get_geo(days: Optional[int] = Query(365, ge=1, le=1825), db: Session = Depends(db_session)) -> dict[str, Any]:
    return geographic_distribution(db, days=days)


@router.get("/cost-trend")
def get_trend(
    days: int = Query(90, ge=7, le=730),
    bucket: str = Query("week", description="week | day"),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    return shipping_cost_trend(db, days=days, bucket=bucket if bucket in ("week", "day") else "week")


@router.get("/3pl-roi")
def get_3pl_roi(days: int = Query(365, ge=30, le=1825), db: Session = Depends(db_session)) -> dict[str, Any]:
    return threepl_roi_estimator(db, days=days)


@router.get("/cx-correlation")
def get_cx_correlation(days: int = Query(30, ge=1, le=365), db: Session = Depends(db_session)) -> dict[str, Any]:
    return cx_shipping_summary(db, days=days)
