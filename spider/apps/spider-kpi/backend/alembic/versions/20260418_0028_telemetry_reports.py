"""Add telemetry_reports table for comprehensive AI-written telemetry analyses

Revision ID: 20260418_0028
Revises: 20260418_0027
Create Date: 2026-04-18 14:00:00.000000+00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "20260418_0028"
down_revision = "20260418_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telemetry_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("report_type", sa.String(length=32), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("body_markdown", sa.Text(), nullable=False),
        sa.Column("sections_json", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("benchmarks_json", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("key_findings_json", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("recommendations_json", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("model", sa.String(length=64)),
        sa.Column("sources_used", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("context_chars", sa.Integer()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("usage_json", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="published", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("report_date", "report_type", name="uq_telemetry_report_date_type"),
    )
    op.create_index("ix_telemetry_reports_date", "telemetry_reports", ["report_date"])


def downgrade() -> None:
    op.drop_index("ix_telemetry_reports_date", table_name="telemetry_reports")
    op.drop_table("telemetry_reports")
