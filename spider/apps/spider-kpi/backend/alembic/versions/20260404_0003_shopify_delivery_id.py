"""add shopify webhook delivery id

Revision ID: 20260404_0003
Revises: 20260401_0002
Create Date: 2026-04-04 21:59:00
"""

from alembic import op
import sqlalchemy as sa

revision = "20260404_0003"
down_revision = "20260401_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shopify_order_events", sa.Column("delivery_id", sa.String(length=128), nullable=True))
    op.create_index("ix_shopify_order_events_delivery_id", "shopify_order_events", ["delivery_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_shopify_order_events_delivery_id", table_name="shopify_order_events")
    op.drop_column("shopify_order_events", "delivery_id")
