"""Add telemetry_anomalies table for trailing-14d modified-z-score detections

Revision ID: 20260418_0029
Revises: 20260418_0028
Create Date: 2026-04-18 15:00:00.000000+00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260418_0029"
down_revision = "20260418_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telemetry_anomalies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("baseline_median", sa.Float(), nullable=False),
        sa.Column("baseline_mad", sa.Float(), nullable=False),
        sa.Column("modified_z_score", sa.Float(), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("sample_size", sa.Integer(), server_default="0", nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("status", sa.String(length=16), server_default="new", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("business_date", "metric", name="uq_telemetry_anomalies_date_metric"),
    )
    op.create_index("ix_telemetry_anomalies_date", "telemetry_anomalies", ["business_date"])
    op.create_index("ix_telemetry_anomalies_severity", "telemetry_anomalies", ["severity"])


def downgrade() -> None:
    op.drop_index("ix_telemetry_anomalies_severity", table_name="telemetry_anomalies")
    op.drop_index("ix_telemetry_anomalies_date", table_name="telemetry_anomalies")
    op.drop_table("telemetry_anomalies")
