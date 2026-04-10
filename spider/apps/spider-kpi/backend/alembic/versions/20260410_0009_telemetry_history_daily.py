"""add telemetry_history_daily

Revision ID: 20260410_0009
Revises: 20260409_0008
Create Date: 2026-04-10 23:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260410_0009"
down_revision = "20260409_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telemetry_history_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("active_devices", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("engaged_devices", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_events", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_rssi", sa.Float(), nullable=True),
        sa.Column("error_events", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("firmware_distribution", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("model_distribution", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("avg_cook_temp", sa.Float(), nullable=True),
        sa.Column("peak_hour_distribution", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="ddb_export_backfill"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("business_date", name="uq_telemetry_history_daily_date"),
    )
    op.create_index("ix_telemetry_history_daily_business_date", "telemetry_history_daily", ["business_date"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_telemetry_history_daily_business_date", table_name="telemetry_history_daily")
    op.drop_table("telemetry_history_daily")
