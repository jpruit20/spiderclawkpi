"""Add index on telemetry_stream_events.created_at

Source-health endpoint runs six aggregate queries filtered by created_at
(COUNT(*) and COUNT(DISTINCT device_id) over 15m / 60m / 24h windows).
Without an index these do sequential scans of the 2M+ row table,
accounting for ~30s of /api/overview latency. Build CONCURRENTLY so
the live DynamoDB-Streams -> Lambda -> telemetry_stream_events writer
is not blocked during the migration.

Revision ID: 20260414_0020
Revises: 20260414_0019
Create Date: 2026-04-14 20:00:00.000000+00:00
"""

from alembic import op


revision = "20260414_0020"
down_revision = "20260414_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_telemetry_stream_events_created_at",
            "telemetry_stream_events",
            ["created_at"],
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_telemetry_stream_events_created_at",
            table_name="telemetry_stream_events",
            postgresql_concurrently=True,
            if_exists=True,
        )
