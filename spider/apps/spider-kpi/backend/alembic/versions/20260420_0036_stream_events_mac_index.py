"""Expression index for MAC lookup on telemetry_stream_events.

Revision ID: 20260420_0036
Revises: 20260420_0035
Create Date: 2026-04-20

Firmware Hub needs per-device drill-down by MAC, but
``telemetry_stream_events.device_id`` is the DynamoDB 32-char hash, not
the MAC. The MAC lives at ``raw_payload->device_data->reported->mac`` —
this migration adds an expression index on that path (lowercased) so
the Firmware Hub can resolve a MAC to its rows in <50ms.

CREATE INDEX CONCURRENTLY requires autocommit (no enclosing transaction),
hence ``autocommit_block``.
"""
from alembic import op


revision = "20260420_0036"
down_revision = "20260420_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS
              ix_telemetry_stream_events_reported_mac
              ON telemetry_stream_events
              ((lower(raw_payload->'device_data'->'reported'->>'mac')))
              WHERE raw_payload->'device_data'->'reported'->>'mac' IS NOT NULL
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_telemetry_stream_events_reported_mac")
