"""Add category column to partner_products.

Revision ID: 20260425_0006
Revises: 20260425_0005
Create Date: 2026-04-22

The 2026 JIT beta only models core charcoal SKUs (titles containing
"lump" or "briquette"). Earlier iterations floated firestarters, logs,
and specialty charcoals (Hex Supernatural, binchotan) as bundle
add-ons, but Joseph scoped that out on 2026-04-22 — the modeling
surface stays simple and strictly Lump vs. Briquette. The new column
still accommodates ``'other'`` as a safety net so the scraper doesn't
drop a future SKU on the floor if we later choose to ingest it.

Nullable on backfill so existing rows don't block the migration;
the scraper backfills on the next refresh pass.
"""
from alembic import op
import sqlalchemy as sa


revision = "20260425_0006"
down_revision = "20260425_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "partner_products",
        sa.Column("category", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("partner_products", "category")
