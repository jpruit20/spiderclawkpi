"""Synthesizer v2: headline_metrics + timeline columns

Adds the JSONB fields the visual dashboard renders (tile-ready
metrics + chronological events). Both default to empty array so
existing rows remain valid before re-synthesis.
"""
from alembic import op
import sqlalchemy as sa


revision = "20260426_0006"
down_revision = "20260426_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE sharepoint_product_intelligence
            ADD COLUMN IF NOT EXISTS headline_metrics jsonb NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN IF NOT EXISTS timeline jsonb NOT NULL DEFAULT '[]'::jsonb
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE sharepoint_product_intelligence DROP COLUMN IF EXISTS timeline, DROP COLUMN IF EXISTS headline_metrics")
