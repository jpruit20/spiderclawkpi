"""Per-user device recents + nickname tags for the Firmware Hub.

Revision ID: 20260422_0001
Revises: 20260421_0001
Create Date: 2026-04-22

Backs the "recently viewed devices" strip and nickname editor on the
Device Drill-down tab. Upserted on every device-view open (unique on
(user_id, mac)) so the list is a natural LRU by ``last_viewed_at``.
"""
from alembic import op
import sqlalchemy as sa


revision = "20260422_0001"
down_revision = "20260421_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "firmware_device_recents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mac", sa.String(length=32), nullable=False),
        sa.Column("nickname", sa.String(length=128)),
        sa.Column("last_viewed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "mac", name="uq_firmware_device_recents_user_mac"),
    )
    op.create_index("ix_firmware_device_recents_user_id", "firmware_device_recents", ["user_id"])
    op.create_index("ix_firmware_device_recents_mac", "firmware_device_recents", ["mac"])
    op.create_index("ix_firmware_device_recents_last_viewed", "firmware_device_recents", ["last_viewed_at"])


def downgrade() -> None:
    op.drop_index("ix_firmware_device_recents_last_viewed", table_name="firmware_device_recents")
    op.drop_index("ix_firmware_device_recents_mac", table_name="firmware_device_recents")
    op.drop_index("ix_firmware_device_recents_user_id", table_name="firmware_device_recents")
    op.drop_table("firmware_device_recents")
