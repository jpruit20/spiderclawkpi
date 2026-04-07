"""add cx actions

Revision ID: 20260407_0005
Revises: 20260407_0004
Create Date: 2026-04-07 14:35:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260407_0005"
down_revision = "20260407_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cx_actions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("trigger_kpi", sa.String(length=64), nullable=False),
        sa.Column("trigger_condition", sa.String(length=128), nullable=False),
        sa.Column("dedup_key", sa.String(length=255), nullable=False),
        sa.Column("owner", sa.String(length=128), nullable=False),
        sa.Column("co_owner", sa.String(length=128), nullable=True),
        sa.Column("escalation_owner", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("required_action", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_close_rule", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("snapshot_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for name, cols in [
        ("ix_cx_actions_trigger_kpi", ["trigger_kpi"]),
        ("ix_cx_actions_dedup_key", ["dedup_key"]),
        ("ix_cx_actions_owner", ["owner"]),
        ("ix_cx_actions_co_owner", ["co_owner"]),
        ("ix_cx_actions_escalation_owner", ["escalation_owner"]),
        ("ix_cx_actions_priority", ["priority"]),
        ("ix_cx_actions_status", ["status"]),
        ("ix_cx_actions_snapshot_timestamp", ["snapshot_timestamp"]),
    ]:
        op.create_index(name, "cx_actions", cols, unique=False)
    op.execute("CREATE UNIQUE INDEX uq_cx_actions_active_dedup_key ON cx_actions (dedup_key) WHERE status IN ('open','in_progress')")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_cx_actions_active_dedup_key")
    for name in [
        "ix_cx_actions_snapshot_timestamp",
        "ix_cx_actions_status",
        "ix_cx_actions_priority",
        "ix_cx_actions_escalation_owner",
        "ix_cx_actions_co_owner",
        "ix_cx_actions_owner",
        "ix_cx_actions_dedup_key",
        "ix_cx_actions_trigger_kpi",
    ]:
        op.drop_index(name, table_name="cx_actions")
    op.drop_table("cx_actions")
