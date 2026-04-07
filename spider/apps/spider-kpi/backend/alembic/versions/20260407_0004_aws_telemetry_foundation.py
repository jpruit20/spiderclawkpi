"""add aws telemetry foundation

Revision ID: 20260407_0004
Revises: 20260404_0003
Create Date: 2026-04-07 11:55:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260407_0004"
down_revision = "20260404_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telemetry_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_event_id", sa.String(length=128), nullable=False),
        sa.Column("device_id", sa.String(length=128), nullable=True),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.Column("grill_type", sa.String(length=128), nullable=True),
        sa.Column("firmware_version", sa.String(length=64), nullable=True),
        sa.Column("target_temp", sa.Float(), nullable=True),
        sa.Column("session_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("session_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("session_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("disconnect_events", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("manual_overrides", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_codes_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("actual_temp_time_series", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("fan_output_time_series", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("temp_stability_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("time_to_stabilization_seconds", sa.Integer(), nullable=True),
        sa.Column("firmware_health_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("session_reliability_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("manual_override_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cook_success", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_event_id", name="uq_telemetry_sessions_source_event_id"),
    )
    op.create_index("ix_telemetry_sessions_source_event_id", "telemetry_sessions", ["source_event_id"], unique=False)
    op.create_index("ix_telemetry_sessions_device_id", "telemetry_sessions", ["device_id"], unique=False)
    op.create_index("ix_telemetry_sessions_user_id", "telemetry_sessions", ["user_id"], unique=False)
    op.create_index("ix_telemetry_sessions_session_id", "telemetry_sessions", ["session_id"], unique=False)
    op.create_index("ix_telemetry_sessions_grill_type", "telemetry_sessions", ["grill_type"], unique=False)
    op.create_index("ix_telemetry_sessions_firmware_version", "telemetry_sessions", ["firmware_version"], unique=False)
    op.create_index("ix_telemetry_sessions_session_start", "telemetry_sessions", ["session_start"], unique=False)
    op.create_index("ix_telemetry_sessions_session_end", "telemetry_sessions", ["session_end"], unique=False)

    op.create_table(
        "telemetry_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("sessions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("connected_users", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cook_success_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("disconnect_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("temp_stability_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("avg_time_to_stabilization_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("manual_override_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("firmware_health_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("session_reliability_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("error_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("business_date", name="uq_telemetry_daily_date"),
    )
    op.create_index("ix_telemetry_daily_business_date", "telemetry_daily", ["business_date"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_telemetry_daily_business_date", table_name="telemetry_daily")
    op.drop_table("telemetry_daily")
    for name in [
        "ix_telemetry_sessions_session_end",
        "ix_telemetry_sessions_session_start",
        "ix_telemetry_sessions_firmware_version",
        "ix_telemetry_sessions_grill_type",
        "ix_telemetry_sessions_session_id",
        "ix_telemetry_sessions_user_id",
        "ix_telemetry_sessions_device_id",
        "ix_telemetry_sessions_source_event_id",
    ]:
        op.drop_index(name, table_name="telemetry_sessions")
    op.drop_table("telemetry_sessions")
