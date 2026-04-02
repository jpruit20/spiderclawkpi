from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel


class SourceHealthOut(BaseModel):
    source: str
    source_type: str
    configured: bool
    enabled: bool
    sync_mode: str
    last_success_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    last_error: Optional[str] = None
    latest_run_status: str
    latest_run_started_at: Optional[datetime] = None
    latest_run_finished_at: Optional[datetime] = None
    latest_records_processed: int
    derived_status: str
    status_summary: str
    stale_minutes: Optional[int] = None
    blocks_connector_health: bool


class AlertOut(BaseModel):
    id: int
    business_date: Optional[date] = None
    source: str
    severity: str
    status: str
    title: str
    message: str
    owner_team: Optional[str] = None
    confidence: float
    metadata_json: dict[str, Any]

    class Config:
        from_attributes = True


class RecommendationOut(BaseModel):
    id: int
    business_date: Optional[date] = None
    owner_team: str
    title: str
    recommended_action: str
    root_cause: Optional[str] = None
    severity: str
    confidence: float
    estimated_impact: Optional[str] = None
    metadata_json: dict[str, Any]

    class Config:
        from_attributes = True


class DiagnosticOut(BaseModel):
    id: int
    business_date: date
    diagnostic_type: str
    severity: str
    confidence: float
    owner_team: Optional[str] = None
    title: str
    summary: str
    root_cause: Optional[str] = None
    details_json: dict[str, Any]

    class Config:
        from_attributes = True


class KPIDailyOut(BaseModel):
    business_date: date
    revenue: float
    orders: int
    average_order_value: float
    sessions: float
    conversion_rate: float
    revenue_per_session: float
    add_to_cart_rate: float
    bounce_rate: float
    purchases: float
    ad_spend: float
    mer: float
    cost_per_purchase: float
    tickets_created: int
    tickets_resolved: int
    open_backlog: int
    first_response_time: float
    resolution_time: float
    sla_breach_rate: float
    csat: float
    reopen_rate: float
    tickets_per_100_orders: float

    class Config:
        from_attributes = True


class DataQualityOut(BaseModel):
    validation_warnings: list[dict[str, Any]]
    source_drift: list[dict[str, Any]]
    missing_data: list[dict[str, Any]]


class OverviewResponse(BaseModel):
    latest_kpi: Optional[KPIDailyOut] = None
    daily_series: list[KPIDailyOut]
    alerts: list[AlertOut]
    diagnostics: list[DiagnosticOut]
    recommendations: list[RecommendationOut]
    source_health: list[SourceHealthOut]
