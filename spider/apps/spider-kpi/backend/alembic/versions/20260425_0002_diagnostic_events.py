"""Diagnostic events table — app-emitted telemetry events.

Revision ID: 20260425_0002
Revises: 20260425_0001
Create Date: 2026-04-25

Replaces the [AUTOMATED] Freshdesk ticket pattern. The Venom app
currently creates Freshdesk tickets for diagnostic events (WiFi
provisioning fails, controller crashes, sensor errors, etc.),
cluttering the human CX queue with ~1,100 tickets (12% of inbound).

This table receives those events via POST /api/diagnostics/event so
the app can migrate off Freshdesk for diagnostic reporting. Freshdesk
stays the destination for actual customer-initiated contacts only.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260425_0002"
down_revision = "20260425_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "diagnostic_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="info"),
        sa.Column("mac", sa.String(12), nullable=True),
        sa.Column("device_id", sa.String(128), nullable=True),
        sa.Column("user_id", sa.String(128), nullable=True),
        sa.Column("firmware_version", sa.String(64), nullable=True),
        sa.Column("app_version", sa.String(32), nullable=True),
        sa.Column("platform", sa.String(16), nullable=True),
        sa.Column("title", sa.String(256), nullable=True),
        sa.Column("details_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(128), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_diagnostic_event_type", "diagnostic_event", ["event_type"])
    op.create_index("ix_diagnostic_event_mac", "diagnostic_event", ["mac"])
    op.create_index("ix_diagnostic_event_created_at", "diagnostic_event", ["created_at"])
    op.create_index("ix_diagnostic_event_severity", "diagnostic_event", ["severity"])
    op.create_index("ix_diagnostic_event_resolved_at", "diagnostic_event", ["resolved_at"])


def downgrade() -> None:
    op.drop_index("ix_diagnostic_event_resolved_at", table_name="diagnostic_event")
    op.drop_index("ix_diagnostic_event_severity", table_name="diagnostic_event")
    op.drop_index("ix_diagnostic_event_created_at", table_name="diagnostic_event")
    op.drop_index("ix_diagnostic_event_mac", table_name="diagnostic_event")
    op.drop_index("ix_diagnostic_event_type", table_name="diagnostic_event")
    op.drop_table("diagnostic_event")
