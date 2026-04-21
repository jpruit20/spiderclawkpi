"""Freshdesk archive: description + conversations for full-text product search.

Revision ID: 20260424_0002
Revises: 20260424_0001
Create Date: 2026-04-24

Adds the body text we were never storing. Prior ingest only kept subject +
metadata, which made product-level complaint searches impossible. Two changes:

* ``freshdesk_tickets`` — adds ``description_text``, ``description_html``,
  plus fetch markers for backfill resumability.
* ``freshdesk_ticket_conversations`` — one row per reply/note on a ticket
  (customer + agent messages). This is where most of the complaint detail
  lives — the initial description only captures the first message.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260424_0002"
down_revision = "20260424_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("freshdesk_tickets", sa.Column("description_text", sa.Text(), nullable=True))
    op.add_column("freshdesk_tickets", sa.Column("description_html", sa.Text(), nullable=True))
    op.add_column("freshdesk_tickets", sa.Column("description_fetched_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("freshdesk_tickets", sa.Column("conversations_fetched_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "freshdesk_ticket_conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket_id", sa.String(64), nullable=False),
        sa.Column("conversation_id", sa.String(64), nullable=False),
        sa.Column("from_email", sa.String(320), nullable=True),
        sa.Column("to_emails", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("incoming", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("private", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("source", sa.String(32), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("created_at_source", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at_source", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("ticket_id", "conversation_id", name="uq_freshdesk_conv_ticket_conv"),
    )
    op.create_index("ix_freshdesk_conv_ticket", "freshdesk_ticket_conversations", ["ticket_id"])
    op.create_index("ix_freshdesk_conv_ticket_created", "freshdesk_ticket_conversations", ["ticket_id", "created_at_source"])
    op.create_index("ix_freshdesk_conv_created", "freshdesk_ticket_conversations", ["created_at_source"])


def downgrade() -> None:
    op.drop_index("ix_freshdesk_conv_created", table_name="freshdesk_ticket_conversations")
    op.drop_index("ix_freshdesk_conv_ticket_created", table_name="freshdesk_ticket_conversations")
    op.drop_index("ix_freshdesk_conv_ticket", table_name="freshdesk_ticket_conversations")
    op.drop_table("freshdesk_ticket_conversations")
    op.drop_column("freshdesk_tickets", "conversations_fetched_at")
    op.drop_column("freshdesk_tickets", "description_fetched_at")
    op.drop_column("freshdesk_tickets", "description_html")
    op.drop_column("freshdesk_tickets", "description_text")
