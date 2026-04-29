"""KPI inbox processing ledger.

One row per IMAP message we've examined. Identity is the RFC 5322
``Message-ID`` header (stable across folder rebuilds, unlike Gmail's
mutable UID). The ledger is the idempotency mechanism — re-polling
the inbox is safe because each message either has a ledger row
(skip) or doesn't (process).

Status semantics:
  * ``processed``  — a parser ran and wrote at least one record
  * ``no_match``   — no sender/subject pattern matched; ignored
  * ``error``      — parser raised; ``error_message`` has the text
  * ``ignored``    — explicitly excluded by config (e.g. spam folder)

The ``raw_headers_json`` field captures From/To/Subject/Date/Message-ID
so we can debug parser misses without re-fetching the message body.
Bodies and attachments are NOT persisted here — parsers extract what
they need and write to their own tables (e.g. fedex_invoice_charges).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260429_0002"
down_revision = "20260429_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processed_emails",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("message_id", sa.Text, nullable=False, unique=True, index=True),
        sa.Column("gmail_uid", sa.BigInteger),
        sa.Column("mailbox", sa.String(64), nullable=False, server_default=sa.text("'INBOX'")),
        sa.Column("subject", sa.Text),
        sa.Column("from_addr", sa.Text),
        sa.Column("to_addr", sa.Text),
        sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("parser_used", sa.String(64)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("records_created", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("error_message", sa.Text),
        sa.Column("attachment_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column(
            "raw_headers_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_processed_emails_status_processed_at",
        "processed_emails",
        ["status", "processed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_processed_emails_status_processed_at",
        table_name="processed_emails",
    )
    op.drop_table("processed_emails")
