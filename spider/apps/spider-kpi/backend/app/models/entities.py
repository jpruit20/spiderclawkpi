from __future__ import annotations

from datetime import date, datetime
from typing import Optional
import uuid

from sqlalchemy import ARRAY, BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func
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


class AuthUser(TimestampMixin, Base):
    __tablename__ = "auth_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    email_domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)


class AuthVerificationChallenge(TimestampMixin, Base):
    __tablename__ = "auth_verification_challenges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    email_domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False, default='verify_email')
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)


class ShopifyOrderEvent(TimestampMixin, Base):
    __tablename__ = "shopify_order_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delivery_id: Mapped[Optional[str]] = mapped_column(String(128), unique=True, index=True)
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
    # `revenue` is net/recognized sales: current_total_price post-refund, cancelled orders zeroed.
    # `gross_revenue` is total_price (pre-refund, pre-cancellation) — matches Shopify admin "Total sales".
    revenue: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    gross_revenue: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    average_order_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    refunds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_discounts: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
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
    # Per-channel spend (2026-04-18). ``channel_metrics_json`` is a
    # flexible catch-all for revenue/orders/roas/impressions per channel
    # when the raw TW payload exposes them — empty on older rows.
    facebook_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    google_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tiktok_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    snapchat_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    pinterest_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    bing_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    twitter_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    reddit_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    linkedin_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    amazon_ads_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    smsbump_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    omnisend_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    postscript_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    taboola_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    outbrain_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    stackadapt_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    adroll_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    impact_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    custom_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    channel_metrics_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


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
    facebook_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    google_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tiktok_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    snapchat_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    pinterest_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    bing_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    twitter_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    reddit_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    linkedin_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    amazon_ads_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    smsbump_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    omnisend_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    postscript_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    taboola_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    outbrain_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    stackadapt_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    adroll_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    impact_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    custom_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    channel_metrics_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


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
    description_text: Mapped[Optional[str]] = mapped_column(Text)
    description_html: Mapped[Optional[str]] = mapped_column(Text)
    description_fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    conversations_fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class FreshdeskTicketConversation(TimestampMixin, Base):
    __tablename__ = "freshdesk_ticket_conversations"
    __table_args__ = (
        UniqueConstraint("ticket_id", "conversation_id", name="uq_freshdesk_conv_ticket_conv"),
        Index("ix_freshdesk_conv_ticket", "ticket_id"),
        Index("ix_freshdesk_conv_ticket_created", "ticket_id", "created_at_source"),
        Index("ix_freshdesk_conv_created", "created_at_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(64), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    from_email: Mapped[Optional[str]] = mapped_column(String(320))
    to_emails: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    incoming: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    private: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(32))
    body_text: Mapped[Optional[str]] = mapped_column(Text)
    body_html: Mapped[Optional[str]] = mapped_column(Text)
    created_at_source: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at_source: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
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


class AppSideUserObservation(TimestampMixin, Base):
    """One-row-per-(source, source_ref_id) raw observation that a particular
    Spider Grills app user was seen on a given business date. Kept long/event-level
    so the daily rollup can be recomputed deterministically when new sources
    are added (e.g. direct app backend DB pull alongside the Freshdesk pull).
    """
    __tablename__ = "app_side_user_observations"
    __table_args__ = (
        UniqueConstraint("source", "source_ref_id", name="uq_app_side_user_observations_source_ref"),
        Index("ix_app_side_user_observations_business_date_source", "business_date", "source"),
        Index("ix_app_side_user_observations_user_key", "user_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # 'freshdesk' | 'app_backend'
    source_ref_id: Mapped[str] = mapped_column(String(128), nullable=False)  # freshdesk ticket_id or backend user id
    user_key: Mapped[str] = mapped_column(String(128), nullable=False)  # sha256(lower(email)) — stable dedup key across sources
    email: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    email_domain: Mapped[Optional[str]] = mapped_column(String(255))
    observed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class AppSideDeviceObservation(TimestampMixin, Base):
    """One-row-per-(source, source_ref_id) raw observation linking an app user to
    a particular Venom device (by MAC) with self-reported context (firmware,
    app version, phone). MAC is normalized (lowercase, colons stripped) so rows
    from Freshdesk and the app backend align for deduplication.
    """
    __tablename__ = "app_side_device_observations"
    __table_args__ = (
        UniqueConstraint("source", "source_ref_id", name="uq_app_side_device_observations_source_ref"),
        Index("ix_app_side_device_observations_business_date_source", "business_date", "source"),
        Index("ix_app_side_device_observations_mac", "mac_normalized"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_ref_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user_key: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    mac_raw: Mapped[Optional[str]] = mapped_column(String(64))
    mac_normalized: Mapped[Optional[str]] = mapped_column(String(64), index=True)  # hex-only lowercase, bridge to Dynamo thingName
    controller_model: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    firmware_version: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    app_version: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    phone_os: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    phone_os_version: Mapped[Optional[str]] = mapped_column(String(32))
    phone_brand: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    phone_model: Mapped[Optional[str]] = mapped_column(String(128))
    observed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class AppSideDaily(TimestampMixin, Base):
    """Per-day rollup of app-side fleet metrics, split by data source so we can
    always tell what came from Freshdesk (passive — users who ran diagnostics)
    vs. what came from the app backend (full active population, once connected).
    Distribution columns are JSONB { value: count }.
    """
    __tablename__ = "app_side_daily"
    __table_args__ = (
        UniqueConstraint("business_date", "source", name="uq_app_side_daily_date_source"),
        Index("ix_app_side_daily_business_date", "business_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # 'freshdesk' | 'app_backend'
    observations: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unique_users: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unique_devices: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    app_version_dist: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    firmware_version_dist: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    controller_model_dist: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    phone_os_dist: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    phone_brand_dist: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    phone_model_dist: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class ClickUpTask(TimestampMixin, Base):
    """One row per ClickUp task_id. Full ``raw_payload`` is stored so we never
    lose fields and can re-derive anything later. Status + priority are
    mirrored as top-level columns for index-friendly filtering.
    """
    __tablename__ = "clickup_tasks"
    __table_args__ = (
        UniqueConstraint("task_id", name="uq_clickup_tasks_task_id"),
        Index("ix_clickup_tasks_status_type", "status_type"),
        Index("ix_clickup_tasks_space_list", "space_id", "list_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    custom_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    name: Mapped[Optional[str]] = mapped_column(String(500))
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    status_type: Mapped[Optional[str]] = mapped_column(String(32))  # 'open' | 'closed' | 'done' | 'custom'
    priority: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    team_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    space_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    space_name: Mapped[Optional[str]] = mapped_column(String(128))
    folder_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    folder_name: Mapped[Optional[str]] = mapped_column(String(128))
    list_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    list_name: Mapped[Optional[str]] = mapped_column(String(128))
    parent_task_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    creator_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    creator_username: Mapped[Optional[str]] = mapped_column(String(128))
    assignees_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    tags_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    custom_fields_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    url: Mapped[Optional[str]] = mapped_column(Text)
    points: Mapped[Optional[float]] = mapped_column(Float)
    time_estimate_ms: Mapped[Optional[int]] = mapped_column(Integer)
    date_created: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    date_updated: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    date_closed: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    date_done: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class ClickUpTaskEvent(TimestampMixin, Base):
    """Append-only log of task snapshots / status changes. Lets us chart status
    transitions and recompute rollups from scratch at any time.
    """
    __tablename__ = "clickup_task_events"
    __table_args__ = (
        Index("ix_clickup_task_events_task_ts", "task_id", "event_timestamp"),
        UniqueConstraint("task_id", "event_type", "event_timestamp", name="uq_clickup_task_events_natural"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    normalized_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class ClickUpTasksDaily(TimestampMixin, Base):
    """Per-(business_date, space_id) rollup for dashboard charts. Kept
    intentionally simple — pages that need richer views can hit the raw
    ``clickup_tasks`` table via the filtered API endpoint.
    """
    __tablename__ = "clickup_tasks_daily"
    __table_args__ = (
        UniqueConstraint("business_date", "space_id", name="uq_clickup_tasks_daily_date_space"),
        Index("ix_clickup_tasks_daily_business_date", "business_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    space_id: Mapped[Optional[str]] = mapped_column(String(64))
    space_name: Mapped[Optional[str]] = mapped_column(String(128))
    tasks_open: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tasks_closed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tasks_overdue: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tasks_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tasks_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status_breakdown: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    priority_breakdown: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    assignee_breakdown: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class SlackChannel(TimestampMixin, Base):
    """Spider Grills Slack workspace channel. Auto-discovered on a schedule and
    via ``channel_created`` events. Archived/renamed channels stay here with
    flags flipped so historical references don't break.
    """
    __tablename__ = "slack_channels"
    __table_args__ = (
        UniqueConstraint("channel_id", name="uq_slack_channels_channel_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    is_private: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_member: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    topic: Mapped[Optional[str]] = mapped_column(Text)
    purpose: Mapped[Optional[str]] = mapped_column(Text)
    num_members: Mapped[Optional[int]] = mapped_column(Integer)
    created_at_source: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class SlackUser(TimestampMixin, Base):
    __tablename__ = "slack_users"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_slack_users_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(128))  # legacy handle
    real_name: Mapped[Optional[str]] = mapped_column(String(128))
    display_name: Mapped[Optional[str]] = mapped_column(String(128))
    email: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    tz: Mapped[Optional[str]] = mapped_column(String(64))
    title: Mapped[Optional[str]] = mapped_column(String(128))
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_app_user: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class SlackMessage(TimestampMixin, Base):
    """Per-message archive. Natural key is (channel_id, ts) — Slack's ts is
    unique within a channel and looks like ``1729442135.123456``.
    """
    __tablename__ = "slack_messages"
    __table_args__ = (
        UniqueConstraint("channel_id", "ts", name="uq_slack_messages_channel_ts"),
        Index("ix_slack_messages_channel_ts", "channel_id", "ts"),
        Index("ix_slack_messages_thread_ts", "thread_ts"),
        Index("ix_slack_messages_user_id", "user_id"),
        Index("ix_slack_messages_ts_ordered", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    ts: Mapped[str] = mapped_column(String(32), nullable=False)  # Slack timestamp
    ts_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    thread_ts: Mapped[Optional[str]] = mapped_column(String(32))
    parent_user_id: Mapped[Optional[str]] = mapped_column(String(32))
    user_id: Mapped[Optional[str]] = mapped_column(String(32))
    bot_id: Mapped[Optional[str]] = mapped_column(String(32))
    subtype: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    text: Mapped[Optional[str]] = mapped_column(Text)
    edited_user_id: Mapped[Optional[str]] = mapped_column(String(32))
    edited_ts: Mapped[Optional[str]] = mapped_column(String(32))
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_files: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reaction_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reply_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mentions_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class SlackReaction(TimestampMixin, Base):
    __tablename__ = "slack_reactions"
    __table_args__ = (
        UniqueConstraint("channel_id", "message_ts", "user_id", "name", name="uq_slack_reactions_natural"),
        Index("ix_slack_reactions_msg", "channel_id", "message_ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    message_ts: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    reacted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class SlackFile(TimestampMixin, Base):
    """Metadata for Slack-hosted files (images / videos / docs) attached to
    messages. The file bytes are NOT stored here — we stream them on demand
    via ``/api/slack/files/{file_id}`` using the bot token. Slack remains the
    source of truth; deletion on their side propagates via ``file_deleted``.
    """
    __tablename__ = "slack_files"
    __table_args__ = (
        UniqueConstraint("file_id", name="uq_slack_files_file_id"),
        Index("ix_slack_files_message", "channel_id", "message_ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_id: Mapped[str] = mapped_column(String(32), nullable=False)
    channel_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    message_ts: Mapped[Optional[str]] = mapped_column(String(32))
    user_id: Mapped[Optional[str]] = mapped_column(String(32))
    name: Mapped[Optional[str]] = mapped_column(String(255))
    title: Mapped[Optional[str]] = mapped_column(String(255))
    mimetype: Mapped[Optional[str]] = mapped_column(String(128))
    filetype: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    size: Mapped[Optional[int]] = mapped_column(Integer)
    url_private: Mapped[Optional[str]] = mapped_column(Text)
    url_private_download: Mapped[Optional[str]] = mapped_column(Text)
    thumb_url: Mapped[Optional[str]] = mapped_column(Text)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at_source: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class SlackActivityDaily(TimestampMixin, Base):
    """Per-(business_date, channel_id) rollup for the pulse cards and weekly
    AI summary. Hour-of-day histogram lives in ``hour_histogram`` JSONB
    so the card can render a sparkline without extra queries.
    """
    __tablename__ = "slack_activity_daily"
    __table_args__ = (
        UniqueConstraint("business_date", "channel_id", name="uq_slack_activity_daily_date_channel"),
        Index("ix_slack_activity_daily_date", "business_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    channel_name: Mapped[Optional[str]] = mapped_column(String(128))
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unique_users: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reaction_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    thread_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reply_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    peak_hour: Mapped[Optional[int]] = mapped_column(Integer)
    hour_histogram: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    top_users_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)


class AIInsight(TimestampMixin, Base):
    """Cross-source daily observations written by the insight engine.

    Each row is one "non-obvious" observation — usually a correlation or
    causation across multiple sources (telemetry + support + sales + social)
    that wouldn't jump out from any single-source view. Evidence, urgency,
    and suggested_action are populated by Claude Opus at generation time.
    """
    __tablename__ = "ai_insights"
    __table_args__ = (
        Index("ix_ai_insights_business_date", "business_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    observation: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    urgency: Mapped[str] = mapped_column(String(16), default="medium", nullable=False, index=True)
    evidence_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    suggested_action: Mapped[Optional[str]] = mapped_column(Text)
    sources_used: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    model: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="new", nullable=False, index=True)  # new | acknowledged | dismissed
    dismissed_reason: Mapped[Optional[str]] = mapped_column(Text)


class TelemetryAnomaly(TimestampMixin, Base):
    """One row per (business_date, metric) when the daily value deviates
    significantly from its trailing-14-day baseline.

    Uses a *modified* z-score (median + MAD), not mean/stdev — fleet
    telemetry is heavy-tailed and non-normal (holiday spikes, weekend
    rhythm, partial days). Rows are idempotent on (business_date, metric).
    """
    __tablename__ = "telemetry_anomalies"
    __table_args__ = (
        UniqueConstraint("business_date", "metric", name="uq_telemetry_anomalies_date_metric"),
        Index("ix_telemetry_anomalies_date", "business_date"),
        Index("ix_telemetry_anomalies_severity", "severity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    # Observed value for the day + baseline stats over the trailing 14 days.
    value: Mapped[float] = mapped_column(Float, nullable=False)
    baseline_median: Mapped[float] = mapped_column(Float, nullable=False)
    baseline_mad: Mapped[float] = mapped_column(Float, nullable=False)
    modified_z_score: Mapped[float] = mapped_column(Float, nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)  # 'high' | 'low'
    severity: Mapped[str] = mapped_column(String(16), nullable=False)  # 'info' | 'warn' | 'critical'
    sample_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="new", nullable=False)  # new | acknowledged | dismissed


class TelemetryReport(TimestampMixin, Base):
    """Comprehensive AI-generated telemetry analysis.

    The first report is a full 2+ year retrospective; subsequent reports
    (monthly on the 1st) compare the most-recent window to the historical
    baseline. Body is multi-page markdown written by Claude Opus 4.7.
    """
    __tablename__ = "telemetry_reports"
    __table_args__ = (
        UniqueConstraint("report_date", "report_type", name="uq_telemetry_report_date_type"),
        Index("ix_telemetry_reports_date", "report_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    report_type: Mapped[str] = mapped_column(String(32), nullable=False)  # comprehensive | monthly
    window_start: Mapped[date] = mapped_column(Date, nullable=False)
    window_end: Mapped[date] = mapped_column(Date, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)  # short executive summary
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)  # full multi-page report
    sections_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)  # [{title, body}] for UI navigation
    benchmarks_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)  # {metric: {value, interpretation}}
    key_findings_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)  # [{title, detail, urgency}]
    recommendations_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)  # [{title, detail, category}]
    model: Mapped[Optional[str]] = mapped_column(String(64))
    sources_used: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    context_chars: Mapped[Optional[int]] = mapped_column(Integer)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    usage_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="published", nullable=False)  # published | superseded


class NotificationSend(TimestampMixin, Base):
    """Log of every push alert (Slack DM, email) we've sent.

    Primary purpose is **deduplication**: before sending an alert about
    subject (signal_id, draft_id, etc.), we check whether we've already
    alerted this recipient about this subject. Secondary purpose is **rate
    limiting**: count recent sends per recipient to enforce a ceiling.
    """
    __tablename__ = "notification_sends"
    __table_args__ = (
        Index("ix_notification_sends_recipient_sent", "recipient", "sent_at"),
        Index("ix_notification_sends_dedup", "channel", "subject_type", "subject_id", "recipient"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)  # 'slack' | 'email'
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)  # slack user_id or email
    subject_type: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. 'issue_signal', 'morning_digest'
    subject_id: Mapped[Optional[str]] = mapped_column(String(128))  # signal id, draft id, or date for digests
    content_hash: Mapped[Optional[str]] = mapped_column(String(64))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class TelemetryStreamEvent(TimestampMixin, Base):
    __tablename__ = "telemetry_stream_events"
    __table_args__ = (UniqueConstraint("source_event_id", name="uq_telemetry_stream_events_source_event_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_event_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    sample_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    stream_event_name: Mapped[Optional[str]] = mapped_column(String(64))
    engaged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    firmware_version: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    grill_type: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    target_temp: Mapped[Optional[float]] = mapped_column(Float)
    current_temp: Mapped[Optional[float]] = mapped_column(Float)
    heating: Mapped[Optional[bool]] = mapped_column(Boolean)
    intensity: Mapped[Optional[float]] = mapped_column(Float)
    rssi: Mapped[Optional[float]] = mapped_column(Float)
    error_codes_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class TelemetrySession(TimestampMixin, Base):
    __tablename__ = "telemetry_sessions"
    __table_args__ = (UniqueConstraint("source_event_id", name="uq_telemetry_sessions_source_event_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_event_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    device_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    grill_type: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    firmware_version: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    target_temp: Mapped[Optional[float]] = mapped_column(Float)
    session_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    session_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    session_duration_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    disconnect_events: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    manual_overrides: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_codes_json: Mapped[dict] = mapped_column(JSONB, default=list, nullable=False)
    actual_temp_time_series: Mapped[dict] = mapped_column(JSONB, default=list, nullable=False)
    fan_output_time_series: Mapped[dict] = mapped_column(JSONB, default=list, nullable=False)
    temp_stability_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    time_to_stabilization_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    firmware_health_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    session_reliability_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    manual_override_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cook_success: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    # 2026-04-18: intent/outcome/PID-quality model. All nullable —
    # re-derivation script backfills from actual_temp_time_series.
    cook_intent: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    cook_outcome: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    held_target: Mapped[Optional[bool]] = mapped_column(Boolean)
    disturbance_count: Mapped[Optional[int]] = mapped_column(Integer)
    total_disturbance_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    avg_recovery_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    in_control_pct: Mapped[Optional[float]] = mapped_column(Float)
    max_overshoot_f: Mapped[Optional[float]] = mapped_column(Float)
    max_undershoot_f: Mapped[Optional[float]] = mapped_column(Float)
    post_reach_samples: Mapped[Optional[int]] = mapped_column(Integer)


class TelemetryDaily(TimestampMixin, Base):
    __tablename__ = "telemetry_daily"
    __table_args__ = (UniqueConstraint("business_date", name="uq_telemetry_daily_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    sessions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    connected_users: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cook_success_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    disconnect_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    temp_stability_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    avg_time_to_stabilization_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    manual_override_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    firmware_health_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    session_reliability_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    error_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class TelemetryHistoryDaily(TimestampMixin, Base):
    __tablename__ = "telemetry_history_daily"
    __table_args__ = (UniqueConstraint("business_date", name="uq_telemetry_history_daily_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    active_devices: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    engaged_devices: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_events: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_rssi: Mapped[Optional[float]] = mapped_column(Float)
    error_events: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    firmware_distribution: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    model_distribution: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    # Pre-classified product-family event counts. Populated alongside
    # model_distribution by materialize_daily.py — this is what UI
    # charts should key on because W:K:22:1:V (the JOEHY V1 AWS model)
    # is split here by shadow heat.t2.max into Weber Kettle vs Huntsman
    # rather than lumped together as in the raw grill_type histogram.
    product_family_distribution: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    avg_cook_temp: Mapped[Optional[float]] = mapped_column(Float)
    peak_hour_distribution: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    # Cook analysis columns (materialized from derived sessions)
    session_count: Mapped[Optional[int]] = mapped_column(Integer)
    successful_sessions: Mapped[Optional[int]] = mapped_column(Integer)
    cook_styles_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    cook_style_details_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    temp_range_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    duration_range_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    unique_devices_seen: Mapped[Optional[int]] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(64), default="ddb_export_backfill", nullable=False)
    # 2026-04-18: intent+outcome+PID-quality daily aggregates.
    cook_intents_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    cook_outcomes_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    held_target_sessions: Mapped[Optional[int]] = mapped_column(Integer)
    target_seeking_sessions: Mapped[Optional[int]] = mapped_column(Integer)
    held_target_rate: Mapped[Optional[float]] = mapped_column(Float)
    avg_in_control_pct: Mapped[Optional[float]] = mapped_column(Float)
    avg_disturbances_per_cook: Mapped[Optional[float]] = mapped_column(Float)
    avg_recovery_seconds: Mapped[Optional[float]] = mapped_column(Float)
    avg_overshoot_f: Mapped[Optional[float]] = mapped_column(Float)


class TelemetryHistoryMonthly(TimestampMixin, Base):
    __tablename__ = "telemetry_history_monthly"
    __table_args__ = (UniqueConstraint("month_start", name="uq_telemetry_history_monthly_month_start"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    month_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    distinct_devices: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    distinct_engaged_devices: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    observed_mac_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="ddb_export_backfill", nullable=False)
    coverage_window_days: Mapped[int] = mapped_column(Integer, default=365, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class KPIDaily(TimestampMixin, Base):
    __tablename__ = "kpi_daily"
    __table_args__ = (UniqueConstraint("business_date", name="uq_kpi_daily_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    revenue: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    gross_revenue: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
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
    refunds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_discounts: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


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


class CXAction(TimestampMixin, Base):
    __tablename__ = "cx_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    trigger_kpi: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    trigger_condition: Mapped[str] = mapped_column(String(128), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    owner: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    co_owner: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    escalation_owner: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    required_action: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open", index=True)
    evidence: Mapped[dict] = mapped_column(JSONB, default=list, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    auto_close_rule: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    snapshot_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


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
    __table_args__ = (UniqueConstraint("platform", "external_id", name="uq_social_mentions_platform_external_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text)
    title: Mapped[Optional[str]] = mapped_column(Text)
    body: Mapped[Optional[str]] = mapped_column(Text)
    author: Mapped[Optional[str]] = mapped_column(String(128))
    subreddit: Mapped[Optional[str]] = mapped_column(String(128))
    engagement_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    comment_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sentiment: Mapped[str] = mapped_column(String(16), default="neutral", nullable=False, index=True)
    sentiment_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    classification: Mapped[str] = mapped_column(String(64), default="unknown", nullable=False, index=True)
    brand_mentioned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    product_mentioned: Mapped[Optional[str]] = mapped_column(String(128))
    competitor_mentioned: Mapped[Optional[str]] = mapped_column(String(128))
    trend_topic: Mapped[Optional[str]] = mapped_column(String(128))
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ClarityPageMetric(TimestampMixin, Base):
    __tablename__ = "clarity_page_metrics"
    __table_args__ = (UniqueConstraint("page_path", "snapshot_date", name="uq_clarity_page_metrics_path_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    page_path: Mapped[Optional[str]] = mapped_column(String(512))
    page_type: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    sessions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    dead_clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    dead_click_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    rage_clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rage_click_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    quick_backs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quick_back_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    script_errors: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    script_error_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    excessive_scroll: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    friction_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)


class DeciTeamMember(TimestampMixin, Base):
    __tablename__ = "deci_team_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    department: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class DeciDomain(TimestampMixin, Base):
    __tablename__ = "deci_domains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="operations")
    default_driver_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("deci_team_members.id"), nullable=True)
    default_executor_ids: Mapped[dict] = mapped_column(JSONB, default=list, nullable=False)
    default_contributor_ids: Mapped[dict] = mapped_column(JSONB, default=list, nullable=False)
    default_informed_ids: Mapped[dict] = mapped_column(JSONB, default=list, nullable=False)
    escalation_owner_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("deci_team_members.id"), nullable=True)
    escalation_threshold_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class DeciDecision(TimestampMixin, Base):
    __tablename__ = "deci_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False, default="project")  # KPI, Project, Initiative, Issue
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_started")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    department: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    driver_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("deci_team_members.id"), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    domain_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("deci_domains.id"), nullable=True, index=True)
    escalation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="none")  # none, warning, escalated
    escalated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cross_functional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # ClickUp linkage — populated when user creates/links a ClickUp task for this decision.
    clickup_task_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    clickup_status_cached: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    clickup_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    clickup_last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Auto-draft provenance — populated when a decision is auto-created from
    # Slack or ClickUp activity. (origin_signal_type, origin_context_key) is
    # the soft dedup key: the next matching IssueSignal updates this decision
    # rather than spawning a new draft.
    origin_signal_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    origin_context_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    auto_drafted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class DeciAssignment(TimestampMixin, Base):
    __tablename__ = "deci_assignments"
    __table_args__ = (UniqueConstraint("decision_id", "member_id", "role", name="uq_deci_assignment"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(36), ForeignKey("deci_decisions.id", ondelete="CASCADE"), nullable=False, index=True)
    member_id: Mapped[int] = mapped_column(Integer, ForeignKey("deci_team_members.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # executor, contributor, informed


class DeciDecisionLog(TimestampMixin, Base):
    __tablename__ = "deci_decision_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(36), ForeignKey("deci_decisions.id", ondelete="CASCADE"), nullable=False, index=True)
    decision_text: Mapped[str] = mapped_column(Text, nullable=False)
    made_by: Mapped[str] = mapped_column(String(128), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class DeciKpiLink(TimestampMixin, Base):
    __tablename__ = "deci_kpi_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(36), ForeignKey("deci_decisions.id", ondelete="CASCADE"), nullable=False, index=True)
    kpi_name: Mapped[str] = mapped_column(String(128), nullable=False)


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


class EmailMessage(TimestampMixin, Base):
    """Normalized archive of email from shared inboxes (info@spidergrills.com
    and any future additions). Input to the lore system — never surfaced as
    a dashboard widget per 2026-04-19 design decision. Feeds archetype
    classification, sender profiles, Event Timeline, and future Opus passes.
    """
    __tablename__ = "email_messages"
    __table_args__ = (UniqueConstraint("message_id", name="uq_email_messages_message_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[str] = mapped_column(String(512), nullable=False)
    gmail_message_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    thread_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    mailbox: Mapped[str] = mapped_column(String(255), nullable=False)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    direction: Mapped[Optional[str]] = mapped_column(String(16))
    from_address: Mapped[Optional[str]] = mapped_column(String(512))
    from_domain: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    to_addresses: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    cc_addresses: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    subject: Mapped[Optional[str]] = mapped_column(Text)
    body_text: Mapped[Optional[str]] = mapped_column(Text)
    body_preview: Mapped[Optional[str]] = mapped_column(String(500))
    snippet: Mapped[Optional[str]] = mapped_column(Text)
    headers_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    labels_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    attachments_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    archetype: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    topic_tags_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    mentioned_entities_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    classified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    raw_size_bytes: Mapped[Optional[int]] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32), default="gmail_api", nullable=False)


class SeasonalityBaseline(TimestampMixin, Base):
    """Per-metric, per-day-of-year historical distribution for seasonal
    interpretation of current values. Built 2026-04-19 as Phase 1 of
    the company-lore surface: every KPI tile gets a hot/cold verdict
    vs the same day-of-year across prior years, every time-series gets
    an optional p25-p75 baseline band. Materialized nightly from
    kpi_daily / telemetry_history_daily / freshdesk_tickets_daily.
    """
    __tablename__ = "seasonality_baselines"
    __table_args__ = (
        UniqueConstraint("metric_name", "day_of_year", name="uq_seasonality_baselines_metric_doy"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    metric_source: Mapped[str] = mapped_column(String(128), nullable=False)
    day_of_year: Mapped[int] = mapped_column(Integer, nullable=False)
    iso_week: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    year_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    p10: Mapped[Optional[float]] = mapped_column(Float)
    p25: Mapped[Optional[float]] = mapped_column(Float)
    p50: Mapped[Optional[float]] = mapped_column(Float)
    p75: Mapped[Optional[float]] = mapped_column(Float)
    p90: Mapped[Optional[float]] = mapped_column(Float)
    mean: Mapped[Optional[float]] = mapped_column(Float)
    stddev: Mapped[Optional[float]] = mapped_column(Float)
    year_samples_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    computed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class EmailSyncState(TimestampMixin, Base):
    """Per-mailbox watermark for incremental Gmail sync. historyId is the
    Gmail-canonical resume point; see
    https://developers.google.com/gmail/api/guides/sync.
    """
    __tablename__ = "email_sync_state"
    __table_args__ = (UniqueConstraint("mailbox", name="uq_email_sync_state_mailbox"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mailbox: Mapped[str] = mapped_column(String(255), nullable=False)
    last_history_id: Mapped[Optional[str]] = mapped_column(String(64))
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[Optional[str]] = mapped_column(String(32))
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    total_imported: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class LoreEvent(TimestampMixin, Base):
    """Institutional-memory timeline of business events. Overlaid on any
    time-series chart so anomalies are explainable at a glance — "revenue
    spiked because of Memorial Day sale", "active_devices dropped because
    of the April firmware bug", "tickets_created doubled when we shipped
    the new probes". Built 2026-04-19 as Phase 1 piece 2 of the company-
    lore surface. Sourced manually (Joseph), from connector signals
    (email/slack/clickup), or auto-extracted by Opus from the email
    archive with a confidence score the human can upgrade/downgrade.
    """
    __tablename__ = "lore_events"
    __table_args__ = (
        UniqueConstraint("title", "start_date", name="uq_lore_events_title_start"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    division: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    confidence: Mapped[str] = mapped_column(String(16), default="confirmed", nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    source_refs_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(128))


class FirmwareIssueTag(TimestampMixin, Base):
    __tablename__ = "firmware_issue_tags"
    __table_args__ = (UniqueConstraint("slug", name="uq_firmware_issue_tags_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(128))


class FirmwareRelease(TimestampMixin, Base):
    __tablename__ = "firmware_releases"
    __table_args__ = (UniqueConstraint("version", name="uq_firmware_releases_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(256))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    addresses_issues: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False, index=True)
    clickup_task_id: Mapped[Optional[str]] = mapped_column(String(64))
    git_commit_sha: Mapped[Optional[str]] = mapped_column(String(64))
    beta_iot_job_id: Mapped[Optional[str]] = mapped_column(String(128))
    gamma_iot_job_ids_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    gamma_plan_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    beta_report_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    beta_cohort_target_size: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    binary_url: Mapped[Optional[str]] = mapped_column(String(1024))
    binary_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    binary_size_bytes: Mapped[Optional[int]] = mapped_column(Integer)
    target_controller_model: Mapped[Optional[str]] = mapped_column(String(32))
    approved_for_alpha: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved_for_beta: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved_for_gamma: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approval_audit_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(128))
    approved_by: Mapped[Optional[str]] = mapped_column(String(128))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class FirmwareDeployLog(TimestampMixin, Base):
    """Audit trail for every firmware OTA attempt.

    One row per device per deploy attempt. Captures preflight results,
    override reasons (if user bypassed a soft check), the AWS IoT job
    id we created, and terminal status.
    """
    __tablename__ = "firmware_deploy_log"
    __table_args__ = (
        Index("ix_firmware_deploy_log_release", "release_id"),
        Index("ix_firmware_deploy_log_device", "device_id"),
        Index("ix_firmware_deploy_log_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("firmware_releases.id", ondelete="RESTRICT"), nullable=False)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False)
    mac: Mapped[Optional[str]] = mapped_column(String(12))
    cohort: Mapped[str] = mapped_column(String(16), nullable=False)  # alpha | beta | gamma
    initiated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    aws_job_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(
        String(32),
        default="pending",
        nullable=False,
    )  # preflight_failed | pending | in_flight | succeeded | failed | rolled_back | aborted | kill_switch_tripped
    target_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_version: Mapped[Optional[str]] = mapped_column(String(64))
    preflight_results_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    override_reasons_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    aws_response_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    queued_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class FirmwareDeployPreviewToken(TimestampMixin, Base):
    """Short-lived token issued by /preview and consumed by /execute.

    Enforces two-phase confirmation: caller must have seen the preflight
    results before executing. Token is single-use and expires in 10 minutes.
    """
    __tablename__ = "firmware_deploy_preview_tokens"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("firmware_releases.id", ondelete="CASCADE"), nullable=False)
    cohort: Mapped[str] = mapped_column(String(16), nullable=False)
    device_ids_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    preflight_results_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class FirmwareDeviceRecent(TimestampMixin, Base):
    """Per-user device drill-down history + nickname tag.

    One row per (user, mac). Upserted every time a user opens a device
    in the Firmware Hub. The ``nickname`` is the user-assigned fast-lookup
    label (e.g. "office grill", "Matías test unit"). ``last_viewed_at``
    drives the recents ordering.
    """
    __tablename__ = "firmware_device_recents"
    __table_args__ = (UniqueConstraint("user_id", "mac", name="uq_firmware_device_recents_user_mac"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False, index=True)
    mac: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    nickname: Mapped[Optional[str]] = mapped_column(String(128))
    last_viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class BetaCohortMember(TimestampMixin, Base):
    __tablename__ = "beta_cohort_members"
    __table_args__ = (UniqueConstraint("release_id", "device_id", name="uq_beta_cohort_release_device"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("firmware_releases.id", ondelete="CASCADE"), nullable=False)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(128))
    candidate_score: Mapped[Optional[float]] = mapped_column(Float)
    candidate_reason_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="invited", nullable=False, index=True)
    invited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    opted_in_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    opt_in_source: Mapped[Optional[str]] = mapped_column(String(32))
    ota_pushed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ota_confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    evaluated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    verdict_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class CookBehaviorBaseline(TimestampMixin, Base):
    """Per (target_temp_band, firmware_version) learned statistics on how
    cooks actually progress. Consumed by ``cook_state_classifier`` to
    replace heuristic ramp budgets and post-reach tolerances. Rebuilt
    nightly from TelemetrySession.

    ``firmware_version`` NULL = "all firmware" rollup row (used when no
    firmware-specific bin has enough samples).
    """
    __tablename__ = "cook_behavior_baselines"
    __table_args__ = (
        UniqueConstraint(
            "target_temp_band", "firmware_version", "baseline_version",
            name="uq_cook_behavior_baselines_band_fw_ver",
        ),
        Index("ix_cook_behavior_baselines_band", "target_temp_band"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_temp_band: Mapped[str] = mapped_column(String(16), nullable=False)
    firmware_version: Mapped[Optional[str]] = mapped_column(String(64))
    baseline_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    # Ramp time (seconds from engage to within ±15°F of target).
    ramp_time_p10: Mapped[Optional[float]] = mapped_column(Float)
    ramp_time_p50: Mapped[Optional[float]] = mapped_column(Float)
    ramp_time_p90: Mapped[Optional[float]] = mapped_column(Float)
    # Steady-state fan intensity (0-100%).
    steady_fan_p10: Mapped[Optional[float]] = mapped_column(Float)
    steady_fan_p50: Mapped[Optional[float]] = mapped_column(Float)
    steady_fan_p90: Mapped[Optional[float]] = mapped_column(Float)
    # Post-reach temp stddev (°F).
    steady_temp_stddev_p50: Mapped[Optional[float]] = mapped_column(Float)
    steady_temp_stddev_p90: Mapped[Optional[float]] = mapped_column(Float)
    # Cool-down rate (°F/min).
    cool_down_rate_p50: Mapped[Optional[float]] = mapped_column(Float)
    # Typical cook duration (seconds).
    typical_duration_p50: Mapped[Optional[float]] = mapped_column(Float)
    computed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class CookBehaviorBacktest(TimestampMixin, Base):
    """Self-evaluation scaffold: on each nightly rebuild, score the
    PRIOR baseline version against the last N sessions — how often did
    actual ramp times, steady fans, etc. fall inside the predicted p10-p90
    bands? Drift metrics surface on the firmware overview.
    """
    __tablename__ = "cook_behavior_backtests"
    __table_args__ = (
        UniqueConstraint("run_at", "target_temp_band", "metric", name="uq_cook_behavior_backtests_run_band_metric"),
        Index("ix_cook_behavior_backtests_run_at", "run_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    baseline_version: Mapped[int] = mapped_column(Integer, nullable=False)
    target_temp_band: Mapped[str] = mapped_column(String(16), nullable=False)
    metric: Mapped[str] = mapped_column(String(32), nullable=False)   # ramp_time | steady_fan | steady_temp_stddev
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    in_band_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    below_band_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    above_band_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    coverage_pct: Mapped[Optional[float]] = mapped_column(Float)
    median_error_pct: Mapped[Optional[float]] = mapped_column(Float)


class FreshdeskCookCorrelation(TimestampMixin, Base):
    """Per-ticket bridge to cook sessions near the ticket's creation time.

    Built by ``freshdesk_cook_correlation`` — for each Freshdesk ticket
    whose requester has a MAC linkage via ``AppSideDeviceObservation``,
    find TelemetrySession rows for that MAC within ±N hours of the
    ticket creation and summarize them. Surfaces on VOC pages: "this
    ticket was opened during a cook that overshot by 85°F".
    """
    __tablename__ = "freshdesk_cook_correlations"
    __table_args__ = (
        UniqueConstraint("ticket_id", name="uq_freshdesk_cook_correlations_ticket"),
        Index("ix_freshdesk_cook_correlations_mac", "mac_normalized"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(64), nullable=False)
    mac_normalized: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    ticket_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    window_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    sessions_matched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    evidence_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    computed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class KlaviyoProfile(TimestampMixin, Base):
    """Mirror of a Klaviyo profile.

    Populated by ``ingestion.connectors.klaviyo``. Agustin's app writes
    per-user device state (``device_types``, ``device_firmware_versions``,
    ``product_ownership``) plus phone platform context into Klaviyo on
    every ``Opened App`` event; this table mirrors that so the dashboard
    can join at the user level without punching a direct route between
    the native app and the backend.
    """
    __tablename__ = "klaviyo_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    klaviyo_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    email: Mapped[Optional[str]] = mapped_column(String(320), index=True)
    phone_number: Mapped[Optional[str]] = mapped_column(String(32))
    first_name: Mapped[Optional[str]] = mapped_column(String(128))
    last_name: Mapped[Optional[str]] = mapped_column(String(128))

    device_types: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list, nullable=False)
    device_firmware_versions: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list, nullable=False)
    product_ownership: Mapped[Optional[str]] = mapped_column(String(128))

    phone_os: Mapped[Optional[str]] = mapped_column(String(16))
    phone_model: Mapped[Optional[str]] = mapped_column(String(64))
    phone_os_version: Mapped[Optional[str]] = mapped_column(String(32))
    phone_brand: Mapped[Optional[str]] = mapped_column(String(64))
    app_version: Mapped[Optional[str]] = mapped_column(String(32))
    expected_next_order_date: Mapped[Optional[str]] = mapped_column(String(32))

    raw_properties: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    klaviyo_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    klaviyo_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    last_event_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class KlaviyoEvent(TimestampMixin, Base):
    """Mirror of a Klaviyo metric event (firehose).

    Keyed by ``klaviyo_event_id``; sync is idempotent via
    ``ON CONFLICT DO NOTHING``. Properties are stored as JSONB because
    Klaviyo event schemas vary by metric (Opened App has app build +
    device model; Placed Order has full Shopify line items).
    """
    __tablename__ = "klaviyo_events"
    __table_args__ = (
        Index("ix_klaviyo_events_metric_datetime", "metric_name", "event_datetime"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    klaviyo_event_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    metric_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    metric_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    klaviyo_profile_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    email: Mapped[Optional[str]] = mapped_column(String(320), index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    event_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    properties: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MicrosoftTenant(TimestampMixin, Base):
    """One row per Microsoft 365 / Azure AD tenant we ingest from.

    Multi-tenant by design: AMW today, Spider Grills' own M365 account
    later. Same multi-tenant Azure AD app (CLIENT_ID + CLIENT_SECRET in
    env) services all of them — only this row needs to land per tenant.
    """
    __tablename__ = "microsoft_tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    primary_domain: Mapped[Optional[str]] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)


class SharepointSite(TimestampMixin, Base):
    """The allowlist + metadata mirror for each granted SharePoint site.

    Add a row here for each AMW SharePoint card the dashboard should
    read. ``Sites.Selected`` on the Azure AD app means Microsoft will
    still refuse to return data for any site we haven't been granted
    via ``POST /sites/{id}/permissions`` — this table is the
    application-level allowlist on top of that platform-level guard.
    """
    __tablename__ = "sharepoint_sites"
    __table_args__ = (
        UniqueConstraint("tenant_id", "site_path", name="uq_sharepoint_sites_tenant_path"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    graph_site_id: Mapped[Optional[str]] = mapped_column(String(256), unique=True, index=True)
    site_path: Mapped[str] = mapped_column(String(255), nullable=False)
    hostname: Mapped[str] = mapped_column(String(128), default="alignmachineworks.sharepoint.com", nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(255))
    web_url: Mapped[Optional[str]] = mapped_column(String(512))
    spider_product: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    default_division: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    granted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    last_sync_error: Mapped[Optional[str]] = mapped_column(Text)


class SharepointDocument(TimestampMixin, Base):
    """Mirror of files + folders inside a SharePoint document library.

    Folder names that map to dashboard divisions get denormalized into
    ``top_level_folder`` so queries don't have to walk the path.
    """
    __tablename__ = "sharepoint_documents"
    __table_args__ = (
        UniqueConstraint("graph_drive_id", "graph_item_id", name="uq_sharepoint_documents_drive_item"),
        Index("ix_sharepoint_documents_modified_div", "dashboard_division", "modified_at_remote"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    graph_site_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    graph_drive_id: Mapped[str] = mapped_column(String(256), nullable=False)
    graph_item_id: Mapped[str] = mapped_column(String(256), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    path: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    is_folder: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    top_level_folder: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    mime_type: Mapped[Optional[str]] = mapped_column(String(128))
    web_url: Mapped[Optional[str]] = mapped_column(String(2048))
    created_by_email: Mapped[Optional[str]] = mapped_column(String(255))
    created_at_remote: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    modified_by_email: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    modified_at_remote: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    spider_product: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    dashboard_division: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    raw_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # Semantic layer (populated by app/services/sharepoint_classify.py)
    archive_status: Mapped[Optional[str]] = mapped_column(String(16), index=True)
    semantic_type: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    parsed_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    classified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class SharepointBomLine(Base):
    """One row per part extracted from a BOM Excel file. The dashboard's
    COGS rollup queries this; the source-of-truth file lives at
    ``document_id`` so users can click through."""
    __tablename__ = "sharepoint_bom_lines"
    __table_args__ = (
        Index("ix_sharepoint_bom_lines_doc_part", "document_id", "part_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(Integer, ForeignKey("sharepoint_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    line_no: Mapped[Optional[int]] = mapped_column(Integer)
    part_number: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    vendor_name: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    qty: Mapped[Optional[float]] = mapped_column(Numeric(14, 4))
    unit: Mapped[Optional[str]] = mapped_column(String(32))
    unit_cost_usd: Mapped[Optional[float]] = mapped_column(Numeric(14, 4))
    total_cost_usd: Mapped[Optional[float]] = mapped_column(Numeric(14, 4))
    currency_raw: Mapped[Optional[str]] = mapped_column(String(8))
    raw_row_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SharepointCanonicalSource(Base):
    """Per ``(data_type, spider_product, dashboard_division)`` the file
    that's the source of truth. Auto-chosen by services/
    sharepoint_canonical.py (newest non-archived BOM) unless a user has
    pinned an override.

    ``data_type`` examples: cogs, bom, vendor_list, design_spec, drawing.
    """
    __tablename__ = "sharepoint_canonical_sources"
    __table_args__ = (
        UniqueConstraint("data_type", "spider_product", "dashboard_division", name="uq_canonical_source_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    spider_product: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    dashboard_division: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    document_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("sharepoint_documents.id", ondelete="SET NULL"))
    auto_chosen: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    override_user: Mapped[Optional[str]] = mapped_column(String(255))
    override_note: Mapped[Optional[str]] = mapped_column(Text)
    override_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class SharepointExtractionRun(Base):
    """Append-only log of "we tried to extract X from this file".
    Supports re-running a single failed file and tracking parser
    regressions across versions."""
    __tablename__ = "sharepoint_extraction_runs"
    __table_args__ = (
        Index("ix_sharepoint_extraction_runs_doc_kind_ran", "document_id", "kind", "ran_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(Integer, ForeignKey("sharepoint_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    parser_version: Mapped[Optional[str]] = mapped_column(String(32))
    lines_extracted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SharepointFileContent(Base):
    """Cached extracted content per document. We re-extract only when
    ``source_modified_at`` advances or ``content_sha256`` changes, so
    the corpus pass is cheap on subsequent runs."""
    __tablename__ = "sharepoint_file_content"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(Integer, ForeignKey("sharepoint_documents.id", ondelete="CASCADE"), nullable=False, unique=True)
    text_content: Mapped[Optional[str]] = mapped_column(Text)
    structure_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    content_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    source_modified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    byte_size: Mapped[Optional[int]] = mapped_column(BigInteger)
    extractor_version: Mapped[str] = mapped_column(String(32), nullable=False, default="content-v1")
    extraction_status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    extraction_error: Mapped[Optional[str]] = mapped_column(Text)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SharepointFileAnalysis(Base):
    """Claude's structured analysis of a single document. The dashboard
    cites specific facts from ``key_facts`` back to this row."""
    __tablename__ = "sharepoint_file_analysis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(Integer, ForeignKey("sharepoint_documents.id", ondelete="CASCADE"), nullable=False, unique=True)
    purpose: Mapped[Optional[str]] = mapped_column(Text)
    key_facts: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    related_part_numbers: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    related_vendors: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    cost_data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    design_data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    decisions: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    data_quality_flags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    model_used: Mapped[Optional[str]] = mapped_column(String(64))
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    analyzer_version: Mapped[str] = mapped_column(String(32), nullable=False, default="analysis-v1")
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SharepointProductIntelligence(Base):
    """Per-product cross-file synthesis. ``narrative_md`` leads the
    intelligence card; the typed sub-payloads drive the structured
    sections; ``citations`` lets the UI link every claim to its source."""
    __tablename__ = "sharepoint_product_intelligence"
    __table_args__ = (
        UniqueConstraint("spider_product", "dashboard_division", name="uq_sp_product_intel_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    spider_product: Mapped[str] = mapped_column(String(64), nullable=False)
    dashboard_division: Mapped[Optional[str]] = mapped_column(String(32))
    narrative_md: Mapped[Optional[str]] = mapped_column(Text)
    cogs_summary: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    design_status: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    vendor_summary: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    data_quality_issues: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    citations: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    headline_metrics: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    timeline: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    files_analyzed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    model_used: Mapped[Optional[str]] = mapped_column(String(64))
    synthesizer_version: Mapped[str] = mapped_column(String(32), nullable=False, default="synth-v1")
    synthesized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SharepointListItem(TimestampMixin, Base):
    """Mirror of structured SharePoint list items (ECRs, task trackers,
    vendor specs, BOM revs — anything that lives in a SharePoint List
    rather than a document library)."""
    __tablename__ = "sharepoint_list_items"
    __table_args__ = (
        UniqueConstraint("graph_list_id", "graph_item_id", name="uq_sharepoint_list_items_list_item"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    graph_site_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    graph_list_id: Mapped[str] = mapped_column(String(256), nullable=False)
    graph_list_name: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    graph_item_id: Mapped[str] = mapped_column(String(256), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(1024))
    created_by_email: Mapped[Optional[str]] = mapped_column(String(255))
    created_at_remote: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    modified_by_email: Mapped[Optional[str]] = mapped_column(String(255))
    modified_at_remote: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    web_url: Mapped[Optional[str]] = mapped_column(String(2048))
    fields: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    spider_product: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    dashboard_division: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AIFeedback(TimestampMixin, Base):
    """One reaction per (user, AI-generated artifact). Closes the loop on
    whether the dashboard's AI outputs actually landed.

    Artifact types:
      * ``ai_insight``       — rows in ``ai_insights``
      * ``deci_draft``       — rows in ``deci_drafts``
      * ``issue_signal``     — rows in ``issue_signals`` (AI-classified ones)
      * ``firmware_verdict`` — entries in ``firmware_releases.beta_report_json``

    Reactions drive the weekly ``ai_self_grade`` pass + per-source
    precision metrics. ``note`` is an optional free-text rationale
    (especially useful on ``wrong``).
    """
    __tablename__ = "ai_feedback"
    __table_args__ = (
        UniqueConstraint("user_email", "artifact_type", "artifact_id", name="uq_ai_feedback_user_artifact"),
        Index("ix_ai_feedback_artifact", "artifact_type", "artifact_id"),
        Index("ix_ai_feedback_reaction_created", "reaction", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    artifact_type: Mapped[str] = mapped_column(String(40), nullable=False)
    artifact_id: Mapped[str] = mapped_column(String(80), nullable=False)
    # acted_on | already_knew | wrong | ignore
    reaction: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text)


class AISelfGrade(Base):
    """Weekly Opus self-evaluation. Reads the last 7d of AI-generated
    artifacts joined to their ``ai_feedback`` reactions and any
    downstream outcomes (ticket resolutions, DECI acceptance, firmware
    verdict updates), writes a per-source precision breakdown plus a
    ``prompt_delta`` — a suggested diff to append to next week's
    insight-engine system prompt.

    ``approved_at`` is null until Joseph explicitly approves via the
    UI. ``applied_at`` is set when the delta is folded into the live
    prompt. Auto-apply is off by design — Opus grading its own output
    and immediately rewriting its own prompt is a tight loop that can
    drift without human supervision.
    """
    __tablename__ = "ai_self_grade"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    window_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    artifacts_scored: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    feedback_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    precision_by_source: Mapped[Optional[dict]] = mapped_column(JSONB)
    rejection_themes: Mapped[Optional[dict]] = mapped_column(JSONB)
    overall_summary: Mapped[Optional[str]] = mapped_column(Text)
    prompt_delta: Mapped[Optional[str]] = mapped_column(Text)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[Optional[str]] = mapped_column(String(320))
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    usage_json: Mapped[Optional[dict]] = mapped_column(JSONB)


class PartnerProduct(TimestampMixin, Base):
    """Upstream partner product catalog — currently just Jealous Devil,
    generic shape so Royal Oak / Kingsford / etc can slot in later.

    A periodic scraper (``app.services.partner_catalog``) pulls the
    partner's public storefront JSON and upserts one row per product
    variant. Prices auto-update whenever the partner changes them.
    """
    __tablename__ = "partner_products"
    __table_args__ = (
        UniqueConstraint("partner", "handle", name="uq_partner_products_partner_handle"),
        Index("ix_partner_products_partner", "partner"),
        Index("ix_partner_products_available", "available"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    partner: Mapped[str] = mapped_column(String(64), nullable=False)
    handle: Mapped[str] = mapped_column(String(256), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    # 'lump' | 'briquette' | 'other' — inferred from title keywords
    fuel_type: Mapped[Optional[str]] = mapped_column(String(16))
    # Catalog bucket used by the JIT modeling UI. For the 2026 beta we
    # only ingest core charcoal SKUs — anything whose title contains
    # "lump" or "briquette". Values: 'lump_charcoal' | 'briquette' |
    # 'other'. Specialty items (Hex Supernatural, binchotan) are
    # deliberately not scraped; if we ever expand the catalog, add the
    # new bucket here rather than overloading 'other'.
    category: Mapped[Optional[str]] = mapped_column(String(32))
    # Bag weight in lb, inferred from the title first and falling back
    # to variants[0].grams × 0.00220462 when the title doesn't spell
    # out a weight (some JD SKUs just say "XL Bag"). None if neither
    # source yields a plausible number.
    bag_size_lb: Mapped[Optional[int]] = mapped_column(Integer)
    retail_price_usd: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    source_url: Mapped[Optional[str]] = mapped_column(String(1024))
    available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class CharcoalJITSubscription(TimestampMixin, Base):
    """A device enrolled in the Charcoal JIT auto-ship program.

    One row per (device, user) pair. A single physical grill paired
    with multiple user accounts could produce multiple device_ids and
    thus multiple subscriptions — that's fine; whichever user signed
    up for JIT is the one who gets billed.

    ``shipping_zip`` is what drives the ambient-temp estimate +
    geo-aware burn tuning once the weather API connector lands. It's
    nullable because at enrollment time we may only have the MAC and
    fuel preference — the user can add/confirm shipping later.

    ``status`` values:
      - ``active``    — regular shipments auto-triggered
      - ``paused``    — user paused (manual resume)
      - ``cancelled`` — ended, retained for audit
    """
    __tablename__ = "charcoal_jit_subscriptions"
    __table_args__ = (
        UniqueConstraint("device_id", "user_key", name="uq_charcoal_jit_device_user"),
        Index("ix_charcoal_jit_status", "status"),
        Index("ix_charcoal_jit_mac", "mac_normalized"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    mac_normalized: Mapped[Optional[str]] = mapped_column(String(12))
    user_key: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    fuel_preference: Mapped[str] = mapped_column(String(16), nullable=False)  # 'lump' | 'briquette'
    bag_size_lb: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    safety_stock_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    # Partner product (Jealous Devil, Royal Oak, etc.) — when set,
    # retail_price + bag_size flow from the scraped catalog and stay in
    # sync automatically. If null, bag_size_lb above is used and price
    # is absent from the financial model.
    partner_product_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("partner_products.id", ondelete="SET NULL"),
    )
    # Spider Grills' cut on the transaction. Default 10%, tunable
    # per subscription so we can model outlier deals.
    margin_pct: Mapped[float] = mapped_column(Float, nullable=False, default=10.0)
    shipping_zip: Mapped[Optional[str]] = mapped_column(String(16))
    shipping_lat: Mapped[Optional[float]] = mapped_column(Float)
    shipping_lon: Mapped[Optional[float]] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    enrolled_by: Mapped[Optional[str]] = mapped_column(String(128))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    # Computed + persisted by the scheduler (to be added in a follow-up):
    last_forecast_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    last_shipped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    next_ship_after: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)


class CharcoalJITInvitation(TimestampMixin, Base):
    """A single beta invitation to one device.

    Invitations are batched: the admin picks cohort params (family,
    min_cooks, lookback, percentile floor) + a max invite count, and the
    batch builder selects the top-N devices, snapshots their burn rate
    and percentile, and writes one row here per device with a shared
    ``batch_id``. The app-side resolves ``invitation_token`` at opt-in
    time and promotes the row to ``accepted`` with a linked
    ``subscription_id``.

    Status values:
      * ``pending``  — sent, neither accepted nor declined yet
      * ``accepted`` — user opted in; ``subscription_id`` set
      * ``declined`` — user actively said no
      * ``expired``  — hit ``expires_at`` without action
      * ``revoked``  — admin pulled back the invite (bad targeting, etc.)
    """
    __tablename__ = "charcoal_jit_invitations"
    __table_args__ = (
        Index("ix_charcoal_jit_invitations_device_id", "device_id"),
        Index("ix_charcoal_jit_invitations_mac", "mac_normalized"),
        Index("ix_charcoal_jit_invitations_status", "status"),
        Index("ix_charcoal_jit_invitations_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    invitation_token: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()),
    )
    device_id: Mapped[Optional[str]] = mapped_column(String(128))
    mac_normalized: Mapped[Optional[str]] = mapped_column(String(12))
    user_key: Mapped[Optional[str]] = mapped_column(String(128))

    # SKU + shipping params snapshotted at invite time.
    partner_product_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("partner_products.id", ondelete="SET NULL"),
    )
    bag_size_lb: Mapped[int] = mapped_column(Integer, nullable=False)
    fuel_preference: Mapped[str] = mapped_column(String(16), nullable=False)
    margin_pct: Mapped[float] = mapped_column(Float, nullable=False, default=10.0)

    # Burn-rate / cohort snapshot — recorded once, never updated.
    addressable_lb_per_month: Mapped[Optional[float]] = mapped_column(Float)
    percentile_at_invite: Mapped[Optional[float]] = mapped_column(Float)
    sessions_in_window_at_invite: Mapped[Optional[int]] = mapped_column(Integer)
    product_family_at_invite: Mapped[Optional[str]] = mapped_column(String(64))
    cohort_params_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    invited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    declined_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    invited_by: Mapped[Optional[str]] = mapped_column(String(128))
    notes: Mapped[Optional[str]] = mapped_column(Text)

    subscription_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("charcoal_jit_subscriptions.id", ondelete="SET NULL"),
    )


class AiNarrative(TimestampMixin, Base):
    """Persistent store for on-demand Opus narratives — the "write 3-5
    actionable observations and cache the result" pattern.

    One row per `kind` (latest wins). Narratives that Joseph or the
    team regenerates from the UI land here so they survive uvicorn
    restarts. Dedicated tables (``AIInsight``, ``AISelfGrade``,
    ``WeeklyGaugeSelection``) still exist for flows that need richer
    schemas — this table is for the simpler "overall_theme +
    observations[]" shape.

    Current kinds:
      - ``alpha_cohort_insight``: firmware program narrative for the
        alpha tester cohort (01.01.90 → 01.01.99). Regenerated from
        the Firmware Hub → Alpha tab.

    Add new kinds freely; no schema change required.
    """
    __tablename__ = "ai_narratives"
    __table_args__ = (
        UniqueConstraint("kind", name="uq_ai_narratives_kind"),
        Index("ix_ai_narratives_generated_at", "generated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[Optional[str]] = mapped_column(String(80))
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    requested_by: Mapped[Optional[str]] = mapped_column(String(128))


class ShipstationStore(Base):
    """One row per ShipStation store. Spider-only stores have
    ``included_in_spider=True`` and are the allowlist the connector
    pulls shipments for. Other companies sharing the same ShipStation
    account stay out of our data."""
    __tablename__ = "shipstation_stores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ss_store_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    store_name: Mapped[str] = mapped_column(String(255), nullable=False)
    marketplace: Mapped[Optional[str]] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    included_in_spider: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    first_shipment_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_shipment_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ShipstationShipment(Base):
    """Mirror of one ShipStation shipment for a Spider order. Powers
    the shipping-cost-into-COGS rollup; ``shipment_cost`` +
    ``insurance_cost`` is what the gross-profit calculator subtracts.
    ``ss_order_number`` is the customer-facing order id which we match
    back to Shopify orders for per-order attribution."""
    __tablename__ = "shipstation_shipments"
    __table_args__ = (
        Index("ix_shipstation_shipments_ship_date_store", "ship_date", "ss_store_id"),
        Index("ix_shipstation_shipments_create_date_store", "create_date", "ss_store_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ss_shipment_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    ss_order_id: Mapped[Optional[int]] = mapped_column(BigInteger, index=True)
    ss_order_number: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    ss_store_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    customer_email: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    shipment_cost: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    insurance_cost: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    carrier_code: Mapped[Optional[str]] = mapped_column(String(64))
    service_code: Mapped[Optional[str]] = mapped_column(String(64))
    package_code: Mapped[Optional[str]] = mapped_column(String(64))
    tracking_number: Mapped[Optional[str]] = mapped_column(String(255))
    ship_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    create_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    void_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    voided: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    weight_oz: Mapped[Optional[float]] = mapped_column(Numeric(10, 3))
    dimensions_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    warehouse_id: Mapped[Optional[int]] = mapped_column(Integer)
    ship_to_state: Mapped[Optional[str]] = mapped_column(String(64))
    ship_to_country: Mapped[Optional[str]] = mapped_column(String(8))
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FedexFreightLtlShipment(Base):
    """One FedEx Freight LTL shipment (Giant Huntsman territory).

    Currently scaffold-only — the dedicated /rate/v1/freight/rates/quotes
    endpoint returns an opaque "Missing requestedShipment" error and
    Joseph confirmed Spider's LTL mostly goes through a separate carrier
    portal anyway. Table stays in place so when the LTL data path
    arrives (FedEx Freight or another carrier) we have a destination.
    """
    __tablename__ = "fedex_freight_ltl_shipments"
    __table_args__ = (
        Index("ix_fedex_ltl_shipments_spider_ship_date", "is_spider", "ship_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pro_number: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    tracking_number: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    ship_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    delivery_date: Mapped[Optional[date]] = mapped_column(Date)
    service_type: Mapped[Optional[str]] = mapped_column(String(64))
    is_spider: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    reference_value: Mapped[Optional[str]] = mapped_column(String(128))
    shipper_account: Mapped[Optional[str]] = mapped_column(String(32))
    shipper_postal_code: Mapped[Optional[str]] = mapped_column(String(16))
    shipper_country: Mapped[Optional[str]] = mapped_column(String(8))
    recipient_postal_code: Mapped[Optional[str]] = mapped_column(String(16))
    recipient_state: Mapped[Optional[str]] = mapped_column(String(64))
    recipient_country: Mapped[Optional[str]] = mapped_column(String(8))
    total_weight_lb: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    freight_class: Mapped[Optional[str]] = mapped_column(String(16))
    piece_count: Mapped[Optional[int]] = mapped_column(Integer)
    packaging_type: Mapped[Optional[str]] = mapped_column(String(32))
    base_charge_usd: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    accessorials_charge_usd: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    total_charge_usd: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    rate_type: Mapped[Optional[str]] = mapped_column(String(32))
    status: Mapped[Optional[str]] = mapped_column(String(32))
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FedexInvoiceCharge(Base):
    """One charge line from a FedEx invoice (parsed out of the FBO
    weekly CSV export — the API doesn't expose invoice data).

    Multiple rows per shipment, one per charge category (BASE / FUEL /
    RESIDENTIAL / DIM_WEIGHT / GSR / PEAK / etc), so the reconciliation
    card can show *why* a shipment was billed at $40 over the
    expected base rate. Joins to shipstation_shipments on tracking_number.
    """
    __tablename__ = "fedex_invoice_charges"
    __table_args__ = (
        UniqueConstraint("invoice_number", "tracking_number", "charge_category", name="uq_fedex_invoice_charges_invoice_tracking_category"),
        Index("ix_fedex_invoice_charges_spider_ship_date", "is_spider", "ship_date"),
        Index("ix_fedex_invoice_charges_tracking_for_join", "tracking_number", "is_spider"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_number: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    invoice_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    invoice_currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    tracking_number: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ship_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    delivery_date: Mapped[Optional[date]] = mapped_column(Date)
    is_spider: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    reference_value: Mapped[Optional[str]] = mapped_column(String(128))
    account_number: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    service_type: Mapped[Optional[str]] = mapped_column(String(64))
    carrier: Mapped[str] = mapped_column(String(16), default="fedex", nullable=False)
    shipper_postal_code: Mapped[Optional[str]] = mapped_column(String(16))
    recipient_postal_code: Mapped[Optional[str]] = mapped_column(String(16))
    recipient_state: Mapped[Optional[str]] = mapped_column(String(64))
    charge_category: Mapped[str] = mapped_column(String(64), nullable=False)
    charge_description: Mapped[Optional[str]] = mapped_column(String(255))
    charge_amount_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    billed_weight_lb: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    dim_weight_lb: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    actual_weight_lb: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FedexGroundEodSummary(Base):
    """Daily Ground End-of-Day close manifest summary.

    Endpoint returned 404 in both sandbox and production for the
    Spider account — likely the account isn't enrolled in Ground EOD
    Close service, or the API surface for it has been deprecated/moved.
    Table stays for the day FBO-export ingest needs a place to put
    summary aggregates separately from per-charge invoice rows.
    """
    __tablename__ = "fedex_ground_eod_summaries"
    __table_args__ = (
        UniqueConstraint("close_date", "account_number", name="uq_fedex_ground_eod_close_account"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    close_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    account_number: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    is_spider: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    total_shipments: Mapped[Optional[int]] = mapped_column(Integer)
    total_pieces: Mapped[Optional[int]] = mapped_column(Integer)
    total_weight_lb: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))
    total_charge_usd: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))
    manifest_id: Mapped[Optional[str]] = mapped_column(String(64))
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FedexRateQuote(Base):
    """One rate-quote audit row per (tracking_number, rate_type, service_type).

    Powers the cross-check card: "what would FedEx say this label
    *should* have cost at LIST or ACCOUNT pricing, given our
    contracted rates and the actual shipper/recipient/weight on the
    ShipStation shipment?" The delta to ShipStation's billed cost
    catches dim-weight surprises, residential adjustments, and
    misconfigured carrier accounts.

    Refresh cadence: rate quotes are valid for the day they're pulled,
    so we cache one row per (tracking, rate_type) and re-pull only
    if the row is older than the daily refresh threshold.
    """
    __tablename__ = "fedex_rate_quotes"
    __table_args__ = (
        UniqueConstraint("tracking_number", "rate_type", "service_type", name="uq_fedex_rate_quotes_tracking_type"),
        Index("ix_fedex_rate_quotes_quoted_at", "quoted_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tracking_number: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    rate_type: Mapped[str] = mapped_column(String(32), nullable=False)  # ACCOUNT or LIST
    service_type: Mapped[Optional[str]] = mapped_column(String(64))
    quoted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    quoted_charge_usd: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    shipstation_charge_usd: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    delta_usd: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class ProcessedEmail(Base):
    """Idempotency ledger for the kpi@spidergrills.ai IMAP poll.

    Identity = RFC 5322 Message-ID. One row per message we've examined,
    regardless of whether a parser matched. Status tells us why a
    message did/didn't produce records; error_message captures parser
    exceptions for debugging without re-fetching the email.
    """
    __tablename__ = "processed_emails"
    __table_args__ = (
        Index("ix_processed_emails_status_processed_at", "status", "processed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    gmail_uid: Mapped[Optional[int]] = mapped_column(BigInteger)
    mailbox: Mapped[str] = mapped_column(String(64), default="INBOX", nullable=False)
    subject: Mapped[Optional[str]] = mapped_column(Text)
    from_addr: Mapped[Optional[str]] = mapped_column(Text)
    to_addr: Mapped[Optional[str]] = mapped_column(Text)
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    parser_used: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    records_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    attachment_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    raw_headers_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PageConfig(Base):
    """Per-user-per-division layout preferences. Each division lead
    edits their own division's row; Joseph can edit any. Audit-logged
    so changes are reversible."""
    __tablename__ = "page_configs"
    __table_args__ = (
        UniqueConstraint("division", "owner_email", name="uq_page_configs_division_owner"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    division: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    owner_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    config_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    audit_log_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[Optional[str]] = mapped_column(String(255))


class KpiTarget(Base):
    """Operator-set target for a KPI metric, optionally bounded to a
    seasonal window. One row per (metric, period). Active resolution
    in services/kpi_targets.py picks the narrowest matching window
    for a given date, with most-recently-created as tiebreaker."""
    __tablename__ = "kpi_targets"
    __table_args__ = (
        Index("ix_kpi_targets_metric_window", "metric_key", "effective_start", "effective_end"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_value: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False, default="min")  # min | max
    effective_start: Mapped[Optional[date]] = mapped_column(Date)
    effective_end: Mapped[Optional[date]] = mapped_column(Date)
    season_label: Mapped[Optional[str]] = mapped_column(String(64))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    division: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    owner_email: Mapped[Optional[str]] = mapped_column(String(255))
    created_by: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class WeeklyGaugeSelection(TimestampMixin, Base):
    """Opus 4.7's weekly pick of the 8 most-important business gauges.

    One row per (iso_week_start, rank). The Monday cron job runs Opus
    against the metric catalog + recent company context and writes 8
    rows for the coming week. Current values are NOT persisted here —
    they're resolved live from the catalog at read time so the gauge
    animates with fresh data every 30 s. This table only stores the
    selection, Opus's rationale, the target + healthy band, and any
    user pin that should override next week's pick.
    """
    __tablename__ = "weekly_gauge_selection"
    __table_args__ = (
        UniqueConstraint("iso_week_start", "rank", name="uq_weekly_gauge_week_rank"),
        Index("ix_weekly_gauge_week", "iso_week_start"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    iso_week_start: Mapped[date] = mapped_column(Date, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    metric_key: Mapped[str] = mapped_column(String(64), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    target_value: Mapped[Optional[float]] = mapped_column(Float)
    healthy_band_low: Mapped[Optional[float]] = mapped_column(Float)
    healthy_band_high: Mapped[Optional[float]] = mapped_column(Float)
    gauge_style: Mapped[str] = mapped_column(String(32), default="radial", nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    selected_by: Mapped[str] = mapped_column(String(32), default="opus-4-7", nullable=False)
    selection_context_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    selected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AggregateCache(TimestampMixin, Base):
    """Materialized-cache row for expensive endpoint payloads.

    Scheduler-driven builders compute aggregates (cx_snapshot, fleet
    metrics, firmware distributions, etc.) and write the resulting JSON
    here keyed by a short contract string (e.g. ``cx:snapshot:v1``).
    API endpoints read this table first and fall back to live compute
    only when the row is missing. ``source_version`` lets us bust a key
    when the builder's output shape changes.
    """
    __tablename__ = "aggregate_cache"
    __table_args__ = (
        UniqueConstraint("cache_key", name="uq_aggregate_cache_key"),
        Index("ix_aggregate_cache_key", "cache_key"),
        Index("ix_aggregate_cache_computed_at", "computed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cache_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    source_version: Mapped[str] = mapped_column(String(32), default="v1", nullable=False)


class DiagnosticEvent(TimestampMixin, Base):
    """App-emitted diagnostic event (WiFi failure, controller error, etc.).

    Replaces the [AUTOMATED] Freshdesk ticket pattern. The Venom app
    posts to /api/diagnostics/event whenever a background diagnostic
    fires — those events used to become Freshdesk tickets and clutter
    the human support queue. Now they land here and surface on the
    Firmware Hub Diagnostics card so engineering can triage without
    polluting CX.
    """
    __tablename__ = "diagnostic_event"
    __table_args__ = (
        Index("ix_diagnostic_event_type", "event_type"),
        Index("ix_diagnostic_event_mac", "mac"),
        Index("ix_diagnostic_event_created_at", "created_at"),
        Index("ix_diagnostic_event_severity", "severity"),
        Index("ix_diagnostic_event_resolved_at", "resolved_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    mac: Mapped[Optional[str]] = mapped_column(String(12))
    device_id: Mapped[Optional[str]] = mapped_column(String(128))
    user_id: Mapped[Optional[str]] = mapped_column(String(128))
    firmware_version: Mapped[Optional[str]] = mapped_column(String(64))
    app_version: Mapped[Optional[str]] = mapped_column(String(32))
    platform: Mapped[Optional[str]] = mapped_column(String(16))
    title: Mapped[Optional[str]] = mapped_column(String(256))
    details_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[Optional[str]] = mapped_column(String(128))
    resolution_note: Mapped[Optional[str]] = mapped_column(Text)
