"""Integration surface for sister services (currently: Shelob).

Read-only re-exposure of a STRICTLY LIMITED subset of telemetry-page
routes, accepting either a dashboard session cookie OR the
X-App-Password header. This keeps every other dashboard route
(/api/overview, /api/cx/*, /api/issues/*, /api/marketing/*, /api/fleet/*,
etc.) firmly behind the dashboard-session-only gate.

What's exposed here mirrors what the dashboard's Telemetry page itself
consumes:
  - /api/integrations/telemetry/summary       — fleet-aggregate summary
  - /api/integrations/telemetry/cook-analysis — cook-window aggregates
  - /api/integrations/telemetry/history-daily — daily fleet history

NOT exposed (stays dashboard-only): fleet/control-health,
firmware/*, executive/*, cx/*, marketing/*, klaviyo/*, shopify/*,
admin/*. To extend Shelob's KPI scope in the future, add a new
explicit route here — never widen the underlying overview.py router.
"""
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_dashboard_or_service_token
from app.schemas.overview import TelemetrySummaryOut
from app.services.telemetry import summarize_telemetry
from app.services.telemetry_history_daily import (
    get_cook_analysis_for_range,
    get_telemetry_history_daily,
)


router = APIRouter(
    prefix="/api/integrations",
    tags=["integrations"],
    dependencies=[Depends(require_dashboard_or_service_token)],
)


@router.get("/telemetry/summary", response_model=TelemetrySummaryOut)
def integrations_telemetry_summary(
    days: int = 30,
    start: str | None = None,
    end: str | None = None,
    db: Session = Depends(db_session),
):
    """Mirror of /api/telemetry/summary (overview.py) without the cache
    branch — sister services don't need the dashboard's cache layer
    and we don't want their reads invalidating it."""
    start_date = date.fromisoformat(start) if start else None
    end_date = date.fromisoformat(end) if end else None
    days = max(1, min(days, 365))
    payload = summarize_telemetry(db, lookback_days=days, start=start_date, end=end_date)
    payload["history_daily"] = get_telemetry_history_daily(
        db,
        limit=days,
        start=start_date,
        end=end_date,
    )
    return payload


@router.get("/telemetry/cook-analysis")
def integrations_telemetry_cook_analysis(
    start: str = "2024-01-01",
    end: str | None = None,
    db: Session = Depends(db_session),
):
    if end is None:
        from datetime import datetime, timezone
        end = datetime.now(timezone.utc).date().isoformat()
    return get_cook_analysis_for_range(db, start, end)


@router.get("/telemetry/history-daily")
def integrations_telemetry_history_daily(db: Session = Depends(db_session)):
    return get_telemetry_history_daily(db)
