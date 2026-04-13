"""Add cook analysis columns to telemetry_history_daily

Pre-materialized cook session classification, temperature/duration
distributions, and unique device counts per day.  Populated by the
nightly materializer and the S3 history import backfill.

Revision ID: 20260414_0019
Revises: 20260413_0018
Create Date: 2026-04-14 00:00:00.000000+00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260414_0019"
down_revision = "20260413_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("telemetry_history_daily", sa.Column("session_count", sa.Integer(), nullable=True))
    op.add_column("telemetry_history_daily", sa.Column("successful_sessions", sa.Integer(), nullable=True))
    op.add_column("telemetry_history_daily", sa.Column("cook_styles_json", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column("telemetry_history_daily", sa.Column("cook_style_details_json", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column("telemetry_history_daily", sa.Column("temp_range_json", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column("telemetry_history_daily", sa.Column("duration_range_json", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column("telemetry_history_daily", sa.Column("unique_devices_seen", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("telemetry_history_daily", "unique_devices_seen")
    op.drop_column("telemetry_history_daily", "duration_range_json")
    op.drop_column("telemetry_history_daily", "temp_range_json")
    op.drop_column("telemetry_history_daily", "cook_style_details_json")
    op.drop_column("telemetry_history_daily", "cook_styles_json")
    op.drop_column("telemetry_history_daily", "successful_sessions")
    op.drop_column("telemetry_history_daily", "session_count")
