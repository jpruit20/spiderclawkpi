"""Email archive table for info@ shared inbox + future mailboxes

Revision ID: 20260419_0032
Revises: 20260418_0031
Create Date: 2026-04-19 13:45:00.000000-04:00

Context (Joseph, 2026-04-19): info@spidergrills.com is a company-wide
shared inbox going back to Spider Grills' founding. 65k+ messages with
3+ years of supplier negotiations, customer escalations, PR, investor
comms, partnership discussions, warranty issues — the operational DNA
of the company that pre-dates every other tool we've integrated.

This table stores the normalized archive. Attachments are recorded as
metadata only (filename + mime type) — we don't store binary blobs,
they live in Google Drive/Gmail anyway. Body text is kept but HTML is
dropped (plain is sufficient for classification + lore context).

Email is INPUT to the lore system, never a dashboard widget per
Joseph's explicit framing — "backend whisper, not widget feed."
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "20260419_0032"
down_revision = "20260418_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        # RFC 5322 Message-ID — globally unique, our idempotency key.
        sa.Column("message_id", sa.String(length=512), nullable=False),
        # Gmail's opaque per-mailbox message id — only unique within
        # the mailbox but cheaper to query against the Gmail API.
        sa.Column("gmail_message_id", sa.String(length=64), nullable=True),
        # Gmail thread id, used to reconstruct conversations.
        sa.Column("thread_id", sa.String(length=64), nullable=True),
        sa.Column("mailbox", sa.String(length=255), nullable=False),

        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        # inbound = received by info@; outbound = sent from info@.
        sa.Column("direction", sa.String(length=16), nullable=True),

        sa.Column("from_address", sa.String(length=512), nullable=True),
        sa.Column("from_domain", sa.String(length=255), nullable=True),
        sa.Column("to_addresses", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("cc_addresses", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("subject", sa.Text(), nullable=True),

        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("body_preview", sa.String(length=500), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),

        sa.Column("headers_json", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("labels_json", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("attachments_json", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),

        sa.Column("archetype", sa.String(length=64), nullable=True),
        sa.Column("topic_tags_json", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("mentioned_entities_json", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("classified_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("raw_size_bytes", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="gmail_api"),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.UniqueConstraint("message_id", name="uq_email_messages_message_id"),
    )
    op.create_index("ix_email_messages_sent_at", "email_messages", ["sent_at"])
    op.create_index("ix_email_messages_from_domain", "email_messages", ["from_domain"])
    op.create_index("ix_email_messages_thread_id", "email_messages", ["thread_id"])
    op.create_index("ix_email_messages_archetype", "email_messages", ["archetype"])
    op.create_index("ix_email_messages_mailbox_sent", "email_messages", ["mailbox", "sent_at"])
    op.create_index("ix_email_messages_gmail_id", "email_messages", ["gmail_message_id"])

    # Per-mailbox watermark so incremental sync knows where to resume.
    # Uses Gmail's historyId (the canonical resume-point per API docs).
    op.create_table(
        "email_sync_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mailbox", sa.String(length=255), nullable=False),
        sa.Column("last_history_id", sa.String(length=64), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(length=32), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("total_imported", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.UniqueConstraint("mailbox", name="uq_email_sync_state_mailbox"),
    )


def downgrade() -> None:
    op.drop_table("email_sync_state")
    op.drop_index("ix_email_messages_gmail_id", table_name="email_messages")
    op.drop_index("ix_email_messages_mailbox_sent", table_name="email_messages")
    op.drop_index("ix_email_messages_archetype", table_name="email_messages")
    op.drop_index("ix_email_messages_thread_id", table_name="email_messages")
    op.drop_index("ix_email_messages_from_domain", table_name="email_messages")
    op.drop_index("ix_email_messages_sent_at", table_name="email_messages")
    op.drop_table("email_messages")
