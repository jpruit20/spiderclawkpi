"""Weekly Priority Gauges — Opus-curated Command Center top strip.

Revision ID: 20260424_0003
Revises: 20260424_0002
Create Date: 2026-04-20

Replaces the static 4-tile top strip on Command Center with an 8-gauge
cluster that Opus 4.7 re-selects every Monday based on what matters
most this week. One row per (iso_week_start, rank 1..8). Live values
come from the metric catalog resolvers at read time — this table only
stores the selection + Opus's rationale + the healthy band / target.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260424_0003"
down_revision = "20260424_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weekly_gauge_selection",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("iso_week_start", sa.Date(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("metric_key", sa.String(64), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("target_value", sa.Float(), nullable=True),
        sa.Column("healthy_band_low", sa.Float(), nullable=True),
        sa.Column("healthy_band_high", sa.Float(), nullable=True),
        sa.Column("gauge_style", sa.String(32), nullable=False, server_default="radial"),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("selected_by", sa.String(32), nullable=False, server_default="opus-4-7"),
        sa.Column("selection_context_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("selected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("iso_week_start", "rank", name="uq_weekly_gauge_week_rank"),
    )
    op.create_index("ix_weekly_gauge_week", "weekly_gauge_selection", ["iso_week_start"])


def downgrade() -> None:
    op.drop_index("ix_weekly_gauge_week", table_name="weekly_gauge_selection")
    op.drop_table("weekly_gauge_selection")
