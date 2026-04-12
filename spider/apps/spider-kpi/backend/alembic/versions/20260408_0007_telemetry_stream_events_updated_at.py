"""add updated_at to telemetry_stream_events

Revision ID: 20260408_0007
Revises: 20260408_0006
Create Date: 2026-04-08 22:58:00
"""

from alembic import op
import sqlalchemy as sa

revision = '20260408_0007'
down_revision = '20260408_0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    column_exists = conn.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'telemetry_stream_events' AND column_name = 'updated_at')"
        )
    ).scalar()
    if not column_exists:
        op.add_column(
            'telemetry_stream_events',
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        )


def downgrade() -> None:
    conn = op.get_bind()
    column_exists = conn.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'telemetry_stream_events' AND column_name = 'updated_at')"
        )
    ).scalar()
    if column_exists:
        op.drop_column('telemetry_stream_events', 'updated_at')
