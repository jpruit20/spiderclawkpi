"""Add ClickUp task tables + DECI clickup linkage columns

  * ``clickup_tasks``        — one row per task_id, full raw_payload preserved
  * ``clickup_task_events``  — append-only snapshot/status-change log
  * ``clickup_tasks_daily``  — per-(date, space) rollup for charts
  * ``deci_decisions``       — adds clickup_task_id + cached status + URL + last_synced_at

Revision ID: 20260416_0023
Revises: 20260416_0022
Create Date: 2026-04-16 00:30:00.000000+00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "20260416_0023"
down_revision = "20260416_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clickup_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("custom_id", sa.String(length=64)),
        sa.Column("name", sa.String(length=500)),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(length=64)),
        sa.Column("status_type", sa.String(length=32)),
        sa.Column("priority", sa.String(length=32)),
        sa.Column("team_id", sa.String(length=64)),
        sa.Column("space_id", sa.String(length=64)),
        sa.Column("space_name", sa.String(length=128)),
        sa.Column("folder_id", sa.String(length=64)),
        sa.Column("folder_name", sa.String(length=128)),
        sa.Column("list_id", sa.String(length=64)),
        sa.Column("list_name", sa.String(length=128)),
        sa.Column("parent_task_id", sa.String(length=64)),
        sa.Column("creator_id", sa.String(length=64)),
        sa.Column("creator_username", sa.String(length=128)),
        sa.Column("assignees_json", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("tags_json", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("custom_fields_json", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("url", sa.Text()),
        sa.Column("points", sa.Float()),
        sa.Column("time_estimate_ms", sa.Integer()),
        sa.Column("date_created", sa.DateTime(timezone=True)),
        sa.Column("date_updated", sa.DateTime(timezone=True)),
        sa.Column("date_closed", sa.DateTime(timezone=True)),
        sa.Column("date_done", sa.DateTime(timezone=True)),
        sa.Column("start_date", sa.DateTime(timezone=True)),
        sa.Column("due_date", sa.DateTime(timezone=True)),
        sa.Column("archived", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("raw_payload", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("task_id", name="uq_clickup_tasks_task_id"),
    )
    for col in ("task_id", "custom_id", "status", "priority", "team_id", "space_id",
                "folder_id", "list_id", "parent_task_id", "creator_id",
                "date_created", "date_updated", "due_date"):
        op.create_index(f"ix_clickup_tasks_{col}", "clickup_tasks", [col])
    op.create_index("ix_clickup_tasks_status_type", "clickup_tasks", ["status_type"])
    op.create_index("ix_clickup_tasks_space_list", "clickup_tasks", ["space_id", "list_id"])

    op.create_table(
        "clickup_task_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("event_timestamp", sa.DateTime(timezone=True)),
        sa.Column("raw_payload", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("normalized_payload", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("task_id", "event_type", "event_timestamp", name="uq_clickup_task_events_natural"),
    )
    op.create_index("ix_clickup_task_events_task_id", "clickup_task_events", ["task_id"])
    op.create_index("ix_clickup_task_events_event_type", "clickup_task_events", ["event_type"])
    op.create_index("ix_clickup_task_events_event_timestamp", "clickup_task_events", ["event_timestamp"])
    op.create_index("ix_clickup_task_events_task_ts", "clickup_task_events", ["task_id", "event_timestamp"])

    op.create_table(
        "clickup_tasks_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("space_id", sa.String(length=64)),
        sa.Column("space_name", sa.String(length=128)),
        sa.Column("tasks_open", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tasks_closed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tasks_overdue", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tasks_created", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tasks_completed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status_breakdown", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("priority_breakdown", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("assignee_breakdown", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("business_date", "space_id", name="uq_clickup_tasks_daily_date_space"),
    )
    op.create_index("ix_clickup_tasks_daily_business_date", "clickup_tasks_daily", ["business_date"])

    op.add_column("deci_decisions", sa.Column("clickup_task_id", sa.String(length=64), nullable=True))
    op.add_column("deci_decisions", sa.Column("clickup_status_cached", sa.String(length=64), nullable=True))
    op.add_column("deci_decisions", sa.Column("clickup_url", sa.Text(), nullable=True))
    op.add_column("deci_decisions", sa.Column("clickup_last_synced_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_deci_decisions_clickup_task_id", "deci_decisions", ["clickup_task_id"])


def downgrade() -> None:
    op.drop_index("ix_deci_decisions_clickup_task_id", table_name="deci_decisions")
    op.drop_column("deci_decisions", "clickup_last_synced_at")
    op.drop_column("deci_decisions", "clickup_url")
    op.drop_column("deci_decisions", "clickup_status_cached")
    op.drop_column("deci_decisions", "clickup_task_id")

    op.drop_index("ix_clickup_tasks_daily_business_date", table_name="clickup_tasks_daily")
    op.drop_table("clickup_tasks_daily")

    op.drop_index("ix_clickup_task_events_task_ts", table_name="clickup_task_events")
    op.drop_index("ix_clickup_task_events_event_timestamp", table_name="clickup_task_events")
    op.drop_index("ix_clickup_task_events_event_type", table_name="clickup_task_events")
    op.drop_index("ix_clickup_task_events_task_id", table_name="clickup_task_events")
    op.drop_table("clickup_task_events")

    op.drop_index("ix_clickup_tasks_space_list", table_name="clickup_tasks")
    op.drop_index("ix_clickup_tasks_status_type", table_name="clickup_tasks")
    for col in ("task_id", "custom_id", "status", "priority", "team_id", "space_id",
                "folder_id", "list_id", "parent_task_id", "creator_id",
                "date_created", "date_updated", "due_date"):
        op.drop_index(f"ix_clickup_tasks_{col}", table_name="clickup_tasks")
    op.drop_table("clickup_tasks")
