"""Add notification_sends table for push-alert dedup + rate limiting

Revision ID: 20260417_0026
Revises: 20260417_0025
Create Date: 2026-04-17 06:00:00.000000+00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "20260417_0026"
down_revision = "20260417_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_sends",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("recipient", sa.String(length=255), nullable=False),
        sa.Column("subject_type", sa.String(length=64), nullable=False),
        sa.Column("subject_id", sa.String(length=128)),
        sa.Column("content_hash", sa.String(length=64)),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("success", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("metadata_json", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_notification_sends_sent_at", "notification_sends", ["sent_at"])
    op.create_index("ix_notification_sends_recipient_sent", "notification_sends", ["recipient", "sent_at"])
    op.create_index("ix_notification_sends_dedup", "notification_sends",
                    ["channel", "subject_type", "subject_id", "recipient"])


def downgrade() -> None:
    op.drop_index("ix_notification_sends_dedup", table_name="notification_sends")
    op.drop_index("ix_notification_sends_recipient_sent", table_name="notification_sends")
    op.drop_index("ix_notification_sends_sent_at", table_name="notification_sends")
    op.drop_table("notification_sends")
