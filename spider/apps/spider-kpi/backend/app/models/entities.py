from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin


class SourceConfig(TimestampMixin, Base):
    __tablename__ = "source_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    configured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sync_mode: Mapped[str] = mapped_column(String(32), default="poll", nullable=False)
    config_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(Text)


class SourceSyncRun(TimestampMixin, Base):
    __tablename__ = "source_sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sync_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    records_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class ShopifyOrderEvent(TimestampMixin, Base):
    __tablename__ = "shopify_order_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    order_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    event_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    business_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    normalized_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class ShopifyOrderDaily(TimestampMixin, Base):
    __tablename__ = "shopify_orders_daily"
    __table_args__ = (UniqueConstraint("business_date", name="uq_shopify_orders_daily_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    orders: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    revenue: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    average_order_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    refunds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    source_run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("source_sync_runs.id"))


class ShopifyAnalyticsIntraday(TimestampMixin, Base):
    __tablename__ = "shopify_analytics_intraday"
    __table_args__ = (Index("ix_shopify_analytics_intraday_ts", "bucket_start", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sessions: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    users: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    conversion_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    revenue: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class ShopifyAnalyticsDaily(TimestampMixin, Base):
    __tablename__ = "shopify_analytics_daily"
    __table_args__ = (UniqueConstraint("business_date", name="uq_shopify_analytics_daily_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    sessions: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    users: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    conversion_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    add_to_cart_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    page_views: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    bounce_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class TWSummaryIntraday(TimestampMixin, Base):
    __tablename__ = "tw_summary_intraday"
    __table_args__ = (Index("ix_tw_summary_intraday_bucket", "bucket_start", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sessions: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    users: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    conversion_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    add_to_cart_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    purchases: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    page_views: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    bounce_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cost_per_session: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cost_per_atc: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    revenue: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    ad_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class TWSummaryDaily(TimestampMixin, Base):
    __tablename__ = "tw_summary_daily"
    __table_args__ = (UniqueConstraint("business_date", name="uq_tw_summary_daily_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    sessions: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    users: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    conversion_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    add_to_cart_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    purchases: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    page_views: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    bounce_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cost_per_session: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cost_per_atc: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    revenue: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    ad_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class TWMetricCatalog(TimestampMixin, Base):
    __tablename__ = "tw_metric_catalog"
    __table_args__ = (UniqueConstraint("metric_id", name="uq_tw_metric_catalog_metric_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    label: Mapped[Optional[str]] = mapped_column(String(255))
    category: Mapped[Optional[str]] = mapped_column(String(128))
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class TWRawPayload(TimestampMixin, Base):
    __tablename__ = "tw_raw_payloads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    request_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    response_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    source_run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("source_sync_runs.id"))


class FreshdeskTicketEvent(TimestampMixin, Base):
    __tablename__ = "freshdesk_ticket_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    normalized_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class FreshdeskTicket(TimestampMixin, Base):
    __tablename__ = "freshdesk_tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    subject: Mapped[Optional[str]] = mapped_column(String(500))
    status: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    priority: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    channel: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    group_name: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    requester_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    agent_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    created_at_source: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    updated_at_source: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    resolved_at_source: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    first_response_hours: Mapped[Optional[float]] = mapped_column(Float)
    resolution_hours: Mapped[Optional[float]] = mapped_column(Float)
    csat_score: Mapped[Optional[float]] = mapped_column(Float)
    tags_json: Mapped[dict] = mapped_column(JSONB, default=list, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class FreshdeskTicketsDaily(TimestampMixin, Base):
    __tablename__ = "freshdesk_tickets_daily"
    __table_args__ = (UniqueConstraint("business_date", name="uq_freshdesk_tickets_daily_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    tickets_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tickets_resolved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unresolved_tickets: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reopened_tickets: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_response_hours: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    resolution_hours: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    sla_breach_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    csat: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class FreshdeskAgentDaily(TimestampMixin, Base):
    __tablename__ = "freshdesk_agent_daily"
    __table_args__ = (UniqueConstraint("business_date", "agent_id", name="uq_freshdesk_agent_daily"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    agent_name: Mapped[Optional[str]] = mapped_column(String(128))
    tickets_resolved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_response_hours: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    resolution_hours: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class FreshdeskGroupsDaily(TimestampMixin, Base):
    __tablename__ = "freshdesk_groups_daily"
    __table_args__ = (UniqueConstraint("business_date", "group_name", name="uq_freshdesk_groups_daily"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    group_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    tickets_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tickets_resolved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unresolved_tickets: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class KPIDaily(TimestampMixin, Base):
    __tablename__ = "kpi_daily"
    __table_args__ = (UniqueConstraint("business_date", name="uq_kpi_daily_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    revenue: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    orders: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    average_order_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    sessions: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    conversion_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    revenue_per_session: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    add_to_cart_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    bounce_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    purchases: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    ad_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    mer: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cost_per_purchase: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tickets_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tickets_resolved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    open_backlog: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_response_time: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    resolution_time: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    sla_breach_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    csat: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    reopen_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tickets_per_100_orders: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class KPIIntraday(TimestampMixin, Base):
    __tablename__ = "kpi_intraday"
    __table_args__ = (Index("ix_kpi_intraday_bucket", "bucket_start", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revenue: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    orders: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sessions: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    conversion_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    average_order_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class DriverDiagnostic(TimestampMixin, Base):
    __tablename__ = "driver_diagnostics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    diagnostic_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    owner_team: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    root_cause: Mapped[Optional[str]] = mapped_column(Text)
    details_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Alert(TimestampMixin, Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    owner_team: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Recommendation(TimestampMixin, Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    owner_team: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    root_cause: Mapped[Optional[str]] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    estimated_impact: Mapped[Optional[str]] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class IssueSignal(TimestampMixin, Base):
    __tablename__ = "issue_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    signal_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class IssueCluster(TimestampMixin, Base):
    __tablename__ = "issue_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cluster_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    owner_team: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    details_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class SocialMention(TimestampMixin, Base):
    __tablename__ = "social_mentions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    url: Mapped[Optional[str]] = mapped_column(Text)
    author: Mapped[Optional[str]] = mapped_column(String(255))
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    sentiment: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    severity: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    topic: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    product: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="new", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class ReviewMention(TimestampMixin, Base):
    __tablename__ = "review_mentions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    url: Mapped[Optional[str]] = mapped_column(Text)
    author: Mapped[Optional[str]] = mapped_column(String(255))
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    rating: Mapped[Optional[float]] = mapped_column(Float)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    sentiment: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    severity: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    topic: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    product: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="new", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class CommunityMessage(TimestampMixin, Base):
    __tablename__ = "community_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    channel: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    author: Mapped[Optional[str]] = mapped_column(String(255))
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    sentiment: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    severity: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    topic: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    product: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="new", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
