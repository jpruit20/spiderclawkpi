"""Add ai_insights table for daily cross-source observations

Revision ID: 20260418_0027
Revises: 20260417_0026
Create Date: 2026-04-18 00:00:00.000000+00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "20260418_0027"
down_revision = "20260417_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_insights",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("observation", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), server_default="0", nullable=False),
        sa.Column("urgency", sa.String(length=16), server_default="medium", nullable=False),
        sa.Column("evidence_json", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("suggested_action", sa.Text()),
        sa.Column("sources_used", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("model", sa.String(length=64)),
        sa.Column("status", sa.String(length=16), server_default="new", nullable=False),
        sa.Column("dismissed_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ai_insights_business_date", "ai_insights", ["business_date"])
    op.create_index("ix_ai_insights_urgency", "ai_insights", ["urgency"])
    op.create_index("ix_ai_insights_status", "ai_insights", ["status"])


def downgrade() -> None:
    op.drop_index("ix_ai_insights_status", table_name="ai_insights")
    op.drop_index("ix_ai_insights_urgency", table_name="ai_insights")
    op.drop_index("ix_ai_insights_business_date", table_name="ai_insights")
    op.drop_table("ai_insights")
