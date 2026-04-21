"""Generic aggregate_cache table — Tier 2 materialized-cache pattern.

Revision ID: 20260425_0001
Revises: 20260424_0003
Create Date: 2026-04-25

One JSONB row per cache key. Writers are background builder jobs that
re-run expensive aggregates on a schedule; readers are API endpoints
that prefer this table and fall back to live compute only when the key
is missing. cache_key is the contract — builders register under a key,
endpoints read by the same key. source_version lets us bust the cache
when a builder's output shape changes.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260425_0001"
down_revision = "20260424_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "aggregate_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cache_key", sa.String(128), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("source_version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("cache_key", name="uq_aggregate_cache_key"),
    )
    op.create_index("ix_aggregate_cache_key", "aggregate_cache", ["cache_key"])
    op.create_index("ix_aggregate_cache_computed_at", "aggregate_cache", ["computed_at"])


def downgrade() -> None:
    op.drop_index("ix_aggregate_cache_computed_at", table_name="aggregate_cache")
    op.drop_index("ix_aggregate_cache_key", table_name="aggregate_cache")
    op.drop_table("aggregate_cache")
