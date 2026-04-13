"""Add total_discounts to shopify_orders_daily and kpi_daily, add refunds to kpi_daily

Shopify provides total_discounts per order. We track it on the daily
aggregation table and roll it up to KPIDaily alongside refunds (which
was already on ShopifyOrderDaily but never promoted to KPIDaily).

Revision ID: 20260413_0018
Revises: 20260412_0017
Create Date: 2026-04-13 00:00:00.000000+00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "20260413_0018"
down_revision = "20260412_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add total_discounts to shopify_orders_daily
    op.add_column(
        "shopify_orders_daily",
        sa.Column("total_discounts", sa.Float(), nullable=False, server_default="0"),
    )

    # Add refunds and total_discounts to kpi_daily
    op.add_column(
        "kpi_daily",
        sa.Column("refunds", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "kpi_daily",
        sa.Column("total_discounts", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("kpi_daily", "total_discounts")
    op.drop_column("kpi_daily", "refunds")
    op.drop_column("shopify_orders_daily", "total_discounts")
