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
    details_json: Optional[dict[str, Any]] = None


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
    refunds: float = 0.0
    total_discounts: float = 0.0
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
    revenue_source: Optional[str] = None
    sessions_source: Optional[str] = None
    orders_source: Optional[str] = None
    is_partial_day: bool = False
    is_fallback_day: bool = False

    class Config:
        from_attributes = True


class DataQualityOut(BaseModel):
    validation_warnings: list[dict[str, Any]]
    source_drift: list[dict[str, Any]]
    missing_data: list[dict[str, Any]]


class TelemetrySummaryOut(BaseModel):
    latest: Optional[dict[str, Any]] = None
    daily: list[dict[str, Any]]
    firmware_health: list[dict[str, Any]]
    grill_type_health: list[dict[str, Any]]
    top_error_codes: list[dict[str, Any]]
    top_issue_patterns: list[dict[str, Any]]
    slice_snapshot: Optional[dict[str, Any]] = None
    collection_metadata: Optional[dict[str, Any]] = None
    confidence: Optional[dict[str, Any]] = None
    analytics: Optional[dict[str, Any]] = None
    history_daily: list[dict[str, Any]] = []


class TelemetryHistoryMonthlyIn(BaseModel):
    month_start: date
    distinct_devices: int
    distinct_engaged_devices: int = 0


class TelemetryHistoryIngestIn(BaseModel):
    window_days: int = 365
    distinct_devices: int = 0
    distinct_engaged_devices: int = 0
    observed_mac_count: int = 0
    monthly: list[TelemetryHistoryMonthlyIn]
    source: str = "ddb_export_backfill"
    export_bucket: Optional[str] = None
    export_prefix: Optional[str] = None
    export_arn: Optional[str] = None
    notes: Optional[str] = None


class TelemetryStreamRecordIn(BaseModel):
    source_event_id: str
    device_id: str
    sample_timestamp: Optional[datetime] = None
    stream_event_name: Optional[str] = None
    engaged: bool = False
    firmware_version: Optional[str] = None
    grill_type: Optional[str] = None
    target_temp: Optional[float] = None
    current_temp: Optional[float] = None
    heating: Optional[bool] = None
    intensity: Optional[float] = None
    rssi: Optional[float] = None
    error_codes_json: list[Any] = []
    raw_payload: dict[str, Any] = {}


class TelemetryStreamIngestIn(BaseModel):
    records: list[TelemetryStreamRecordIn]


class CXActionOut(BaseModel):
    id: str
    trigger_kpi: str
    trigger_condition: str
    dedup_key: str
    owner: str
    co_owner: Optional[str] = None
    escalation_owner: Optional[str] = None
    title: str
    required_action: str
    priority: str
    status: str
    evidence: list[Any]
    opened_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None
    auto_close_rule: dict[str, Any]
    snapshot_timestamp: datetime

    class Config:
        from_attributes = True


class CXMetricOut(BaseModel):
    key: str
    label: str
    owner: str
    current: float
    target: float
    delta: float
    trend7d: float
    trend30d: float
    status: str
    confidence: Optional[str] = None
    trigger_condition: Optional[str] = None
    critical_immediate: Optional[bool] = None
    consecutive_bad_days: Optional[int] = None
    consecutive_green_days: Optional[int] = None
    snapshot_timestamp: datetime


class CXInsightOut(BaseModel):
    text: str
    evidence: list[str]
    snapshot_timestamp: datetime


class CXTeamLoadOut(BaseModel):
    name: str
    tickets_closed_per_day: float
    active_queue_size: int
    throughput_ratio: float
    avg_close_time: float
    reopen_rate: float
    share_pct: float
    snapshot_timestamp: datetime


class CXSnapshotOut(BaseModel):
    snapshot_timestamp: Optional[datetime] = None
    header_metrics: list[CXMetricOut]
    grid_metrics: list[CXMetricOut]
    actions: list[CXActionOut]
    today_focus: list[CXActionOut]
    team_load: list[CXTeamLoadOut]
    insights: list[CXInsightOut]


class CXActionUpdateIn(BaseModel):
    status: str


class OverviewResponse(BaseModel):
    latest_kpi: Optional[KPIDailyOut] = None
    daily_series: list[KPIDailyOut]
    alerts: list[AlertOut]
    diagnostics: list[DiagnosticOut]
    recommendations: list[RecommendationOut]
    source_health: list[SourceHealthOut]
    telemetry: Optional[TelemetrySummaryOut] = None
