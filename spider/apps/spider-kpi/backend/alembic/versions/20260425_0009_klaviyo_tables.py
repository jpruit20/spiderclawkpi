"""Add klaviyo_profiles + klaviyo_events tables.

Revision ID: 20260425_0009
Revises: 20260425_0008
Create Date: 2026-04-24

Klaviyo is the canonical intermediary between the native grill app
(Agustin's side) and the dashboard. The app writes user-level device
ownership, firmware versions, and lifecycle events (Opened App, First
Cooking Session, etc.) to Klaviyo profiles and metrics; the dashboard
reads from Klaviyo here so we pick up per-user context that the raw
AWS telemetry stream can't provide — notably Giant Huntsman vs
Huntsman (from Shopify Placed Order line items) and true app DAU/MAU
(distinct from telemetry-reporting device count).

Two tables:

* ``klaviyo_profiles`` — one row per Klaviyo profile, keyed by
  ``klaviyo_id``. Holds the stable user identity (email, external_id
  = ``sg-app-NNNNN``), the app-reported device state (deviceTypes[],
  deviceFirmwareVersions[]), phone platform, Product Ownership label,
  and the last time the app phoned home.

* ``klaviyo_events`` — time-series event firehose, keyed by
  ``klaviyo_event_id``. Joined to ``klaviyo_profiles`` via
  ``klaviyo_profile_id``. Properties are stored as JSONB for
  flexibility (Klaviyo event schemas evolve).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260425_0009"
down_revision = "20260425_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "klaviyo_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("klaviyo_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("external_id", sa.String(128), nullable=True, index=True),
        sa.Column("email", sa.String(320), nullable=True, index=True),
        sa.Column("phone_number", sa.String(32), nullable=True),
        sa.Column("first_name", sa.String(128), nullable=True),
        sa.Column("last_name", sa.String(128), nullable=True),
        # App-reported per-device state. Arrays because one profile can
        # own multiple Venom controllers under a single account.
        sa.Column("device_types", postgresql.ARRAY(sa.String(64)), nullable=False, server_default="{}"),
        sa.Column("device_firmware_versions", postgresql.ARRAY(sa.String(32)), nullable=False, server_default="{}"),
        sa.Column("product_ownership", sa.String(128), nullable=True),
        # Mobile platform context for support/fleet views.
        sa.Column("phone_os", sa.String(16), nullable=True),
        sa.Column("phone_model", sa.String(64), nullable=True),
        sa.Column("phone_os_version", sa.String(32), nullable=True),
        sa.Column("phone_brand", sa.String(64), nullable=True),
        sa.Column("app_version", sa.String(32), nullable=True),
        sa.Column("expected_next_order_date", sa.String(32), nullable=True),
        # Full Klaviyo properties blob — one place to look when adding
        # new fields without waiting on a migration.
        sa.Column("raw_properties", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("klaviyo_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("klaviyo_updated_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )

    op.create_table(
        "klaviyo_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("klaviyo_event_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("metric_id", sa.String(32), nullable=False, index=True),
        sa.Column("metric_name", sa.String(128), nullable=False, index=True),
        sa.Column("klaviyo_profile_id", sa.String(64), nullable=True, index=True),
        sa.Column("email", sa.String(320), nullable=True, index=True),
        sa.Column("external_id", sa.String(128), nullable=True, index=True),
        sa.Column("event_datetime", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    # Composite index for the "events by metric in a time range" query
    # pattern that drives DAU/MAU + cross-referencing endpoints.
    op.create_index(
        "ix_klaviyo_events_metric_datetime",
        "klaviyo_events",
        ["metric_name", "event_datetime"],
    )


def downgrade() -> None:
    op.drop_index("ix_klaviyo_events_metric_datetime", table_name="klaviyo_events")
    op.drop_table("klaviyo_events")
    op.drop_table("klaviyo_profiles")
