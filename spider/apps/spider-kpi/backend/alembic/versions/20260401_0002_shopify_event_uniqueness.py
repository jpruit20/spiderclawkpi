"""add shopify event uniqueness index

Revision ID: 20260401_0002
Revises: 20260331_0001
Create Date: 2026-04-01 10:35:00
"""

from alembic import op
import sqlalchemy as sa

revision = "20260401_0002"
down_revision = "20260331_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_shopify_order_events_type_order_ts",
        "shopify_order_events",
        ["event_type", "order_id", "event_timestamp"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_shopify_order_events_type_order_ts", table_name="shopify_order_events")
