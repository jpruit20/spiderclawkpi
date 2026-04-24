"""Add product_family_distribution to telemetry_history_daily.

Revision ID: 20260425_0008
Revises: 20260425_0007
Create Date: 2026-04-24

Charts keyed on the raw ``grill_type`` histogram (``model_distribution``)
could not tell Huntsman apart from Weber Kettle on V1 JOEHY hardware,
because both share the AWS model string ``W:K:22:1:V``. The daily
materializer now pre-classifies each device with the full
product-taxonomy pipeline (shadow ``heat.t2.max`` → firmware history →
current firmware) and emits per-family *event* counts here. The raw
``model_distribution`` column is preserved for debug.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260425_0008"
down_revision = "20260425_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "telemetry_history_daily",
        sa.Column(
            "product_family_distribution",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("telemetry_history_daily", "product_family_distribution")
