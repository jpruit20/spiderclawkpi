"""Persistent store for on-demand Opus narratives.

Revision ID: 20260425_0003
Revises: 20260425_0002
Create Date: 2026-04-21

Replaces the per-process in-memory `_ALPHA_INSIGHT_CACHE` so narratives
survive uvicorn restarts. One row per `kind` (unique). Payload is
JSONB — the "overall_theme + observations[]" shape. Grows slowly;
current scale is one row per narrative category.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260425_0003"
down_revision = "20260425_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_narratives",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("model", sa.String(80), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("requested_by", sa.String(128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("kind", name="uq_ai_narratives_kind"),
    )
    op.create_index(
        "ix_ai_narratives_generated_at",
        "ai_narratives",
        ["generated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_narratives_generated_at", table_name="ai_narratives")
    op.drop_table("ai_narratives")
