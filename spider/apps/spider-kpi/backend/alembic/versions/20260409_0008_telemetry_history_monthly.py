"""add telemetry_history_monthly

Revision ID: 20260409_0008
Revises: 20260408_0007
Create Date: 2026-04-09 11:20:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260409_0008"
down_revision = "20260408_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telemetry_history_monthly",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("month_start", sa.Date(), nullable=False),
        sa.Column("distinct_devices", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("distinct_engaged_devices", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("observed_mac_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="ddb_export_backfill"),
        sa.Column("coverage_window_days", sa.Integer(), nullable=False, server_default="365"),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("month_start", name="uq_telemetry_history_monthly_month_start"),
    )
    op.create_index("ix_telemetry_history_monthly_month_start", "telemetry_history_monthly", ["month_start"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_telemetry_history_monthly_month_start", table_name="telemetry_history_monthly")
    op.drop_table("telemetry_history_monthly")
