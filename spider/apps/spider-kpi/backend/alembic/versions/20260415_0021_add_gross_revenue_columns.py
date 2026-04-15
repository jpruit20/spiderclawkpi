"""Add gross_revenue to shopify_orders_daily and kpi_daily

Shopify admin's "Total sales" report counts orders at their original
total_price (including items later refunded or cancelled). Our existing
`revenue` column sums current_total_price with cancelled orders zeroed,
matching Shopify "Net sales" more closely. Add gross_revenue so the
dashboard can show both figures side-by-side and reconcile against the
Shopify admin dashboard directly.

Revision ID: 20260415_0021
Revises: 20260414_0020
Create Date: 2026-04-15 04:30:00.000000+00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "20260415_0021"
down_revision = "20260414_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shopify_orders_daily",
        sa.Column("gross_revenue", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "kpi_daily",
        sa.Column("gross_revenue", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("kpi_daily", "gross_revenue")
    op.drop_column("shopify_orders_daily", "gross_revenue")
