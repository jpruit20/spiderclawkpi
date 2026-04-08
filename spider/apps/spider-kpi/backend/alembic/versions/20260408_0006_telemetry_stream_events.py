"""telemetry stream event store

Revision ID: 20260408_0006
Revises: 20260407_0005
Create Date: 2026-04-08 16:58:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260408_0006'
down_revision = '20260407_0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'telemetry_stream_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('source_event_id', sa.String(length=255), nullable=False, unique=True),
        sa.Column('device_id', sa.String(length=255), nullable=False, index=True),
        sa.Column('sample_timestamp', sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column('stream_event_name', sa.String(length=64), nullable=True),
        sa.Column('engaged', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('firmware_version', sa.String(length=64), nullable=True),
        sa.Column('grill_type', sa.String(length=64), nullable=True),
        sa.Column('target_temp', sa.Float(), nullable=True),
        sa.Column('current_temp', sa.Float(), nullable=True),
        sa.Column('heating', sa.Boolean(), nullable=True),
        sa.Column('intensity', sa.Float(), nullable=True),
        sa.Column('rssi', sa.Float(), nullable=True),
        sa.Column('error_codes_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('raw_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )


def downgrade() -> None:
    op.drop_table('telemetry_stream_events')
