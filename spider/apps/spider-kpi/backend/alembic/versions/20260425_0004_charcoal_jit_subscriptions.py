"""Charcoal JIT program enrollment.

Revision ID: 20260425_0004
Revises: 20260425_0003
Create Date: 2026-04-22

One row per (device, user) pair enrolled in the auto-ship program.
Drives the future scheduler that generates draft Shopify orders when
trailing burn rate + lead time + safety stock say a shipment is due.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260425_0004"
down_revision = "20260425_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "charcoal_jit_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.String(128), nullable=True),
        sa.Column("mac_normalized", sa.String(12), nullable=True),
        sa.Column("user_key", sa.String(128), nullable=True),
        sa.Column("fuel_preference", sa.String(16), nullable=False),
        sa.Column("bag_size_lb", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("lead_time_days", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("safety_stock_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("shipping_zip", sa.String(16), nullable=True),
        sa.Column("shipping_lat", sa.Float(), nullable=True),
        sa.Column("shipping_lon", sa.Float(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("enrolled_by", sa.String(128), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "last_forecast_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("last_shipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_ship_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("device_id", "user_key", name="uq_charcoal_jit_device_user"),
    )
    op.create_index("ix_charcoal_jit_subscriptions_device_id", "charcoal_jit_subscriptions", ["device_id"])
    op.create_index("ix_charcoal_jit_subscriptions_user_key", "charcoal_jit_subscriptions", ["user_key"])
    op.create_index("ix_charcoal_jit_subscriptions_mac", "charcoal_jit_subscriptions", ["mac_normalized"])
    op.create_index("ix_charcoal_jit_status", "charcoal_jit_subscriptions", ["status"])
    op.create_index("ix_charcoal_jit_next_ship_after", "charcoal_jit_subscriptions", ["next_ship_after"])


def downgrade() -> None:
    op.drop_index("ix_charcoal_jit_next_ship_after", table_name="charcoal_jit_subscriptions")
    op.drop_index("ix_charcoal_jit_status", table_name="charcoal_jit_subscriptions")
    op.drop_index("ix_charcoal_jit_subscriptions_mac", table_name="charcoal_jit_subscriptions")
    op.drop_index("ix_charcoal_jit_subscriptions_user_key", table_name="charcoal_jit_subscriptions")
    op.drop_index("ix_charcoal_jit_subscriptions_device_id", table_name="charcoal_jit_subscriptions")
    op.drop_table("charcoal_jit_subscriptions")
