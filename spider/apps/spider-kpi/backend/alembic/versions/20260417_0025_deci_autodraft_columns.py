"""Add DECI auto-draft provenance columns

Adds ``origin_signal_type``, ``origin_context_key``, ``auto_drafted_at`` to
``deci_decisions`` so the auto-draft engine can dedupe: a later IssueSignal
with the same (source_type, context_key) updates an already-open decision
instead of creating another draft.

Revision ID: 20260417_0025
Revises: 20260417_0024
Create Date: 2026-04-17 00:30:00.000000+00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260417_0025"
down_revision = "20260417_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deci_decisions", sa.Column("origin_signal_type", sa.String(length=64), nullable=True))
    op.add_column("deci_decisions", sa.Column("origin_context_key", sa.String(length=128), nullable=True))
    op.add_column("deci_decisions", sa.Column("auto_drafted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_deci_decisions_origin_signal_type", "deci_decisions", ["origin_signal_type"])
    op.create_index("ix_deci_decisions_origin_context_key", "deci_decisions", ["origin_context_key"])
    op.create_index("ix_deci_decisions_auto_drafted_at", "deci_decisions", ["auto_drafted_at"])


def downgrade() -> None:
    op.drop_index("ix_deci_decisions_auto_drafted_at", table_name="deci_decisions")
    op.drop_index("ix_deci_decisions_origin_context_key", table_name="deci_decisions")
    op.drop_index("ix_deci_decisions_origin_signal_type", table_name="deci_decisions")
    op.drop_column("deci_decisions", "auto_drafted_at")
    op.drop_column("deci_decisions", "origin_context_key")
    op.drop_column("deci_decisions", "origin_signal_type")
