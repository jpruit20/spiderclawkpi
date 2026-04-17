"""Add Slack ingestion tables

  * ``slack_channels``         — workspace channel inventory
  * ``slack_users``            — user directory
  * ``slack_messages``         — per-message archive (full body, raw_payload)
  * ``slack_reactions``        — per-(message, user, name) reaction rows
  * ``slack_files``            — file metadata (bytes streamed on demand)
  * ``slack_activity_daily``   — per-(date, channel) rollup for pulse cards

Revision ID: 20260417_0024
Revises: 20260416_0023
Create Date: 2026-04-17 00:00:00.000000+00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "20260417_0024"
down_revision = "20260416_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "slack_channels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("channel_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128)),
        sa.Column("is_private", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_archived", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_member", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("topic", sa.Text()),
        sa.Column("purpose", sa.Text()),
        sa.Column("num_members", sa.Integer()),
        sa.Column("created_at_source", sa.DateTime(timezone=True)),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("raw_payload", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("channel_id", name="uq_slack_channels_channel_id"),
    )
    op.create_index("ix_slack_channels_channel_id", "slack_channels", ["channel_id"])
    op.create_index("ix_slack_channels_name", "slack_channels", ["name"])
    op.create_index("ix_slack_channels_is_archived", "slack_channels", ["is_archived"])

    op.create_table(
        "slack_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128)),
        sa.Column("real_name", sa.String(length=128)),
        sa.Column("display_name", sa.String(length=128)),
        sa.Column("email", sa.String(length=255)),
        sa.Column("tz", sa.String(length=64)),
        sa.Column("title", sa.String(length=128)),
        sa.Column("is_bot", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_app_user", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("raw_payload", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", name="uq_slack_users_user_id"),
    )
    op.create_index("ix_slack_users_user_id", "slack_users", ["user_id"])
    op.create_index("ix_slack_users_email", "slack_users", ["email"])
    op.create_index("ix_slack_users_is_deleted", "slack_users", ["is_deleted"])

    op.create_table(
        "slack_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("channel_id", sa.String(length=32), nullable=False),
        sa.Column("ts", sa.String(length=32), nullable=False),
        sa.Column("ts_dt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("thread_ts", sa.String(length=32)),
        sa.Column("parent_user_id", sa.String(length=32)),
        sa.Column("user_id", sa.String(length=32)),
        sa.Column("bot_id", sa.String(length=32)),
        sa.Column("subtype", sa.String(length=64)),
        sa.Column("text", sa.Text()),
        sa.Column("edited_user_id", sa.String(length=32)),
        sa.Column("edited_ts", sa.String(length=32)),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("has_files", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("file_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reaction_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reply_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("mentions_json", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("raw_payload", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("channel_id", "ts", name="uq_slack_messages_channel_ts"),
    )
    op.create_index("ix_slack_messages_channel_ts", "slack_messages", ["channel_id", "ts"])
    op.create_index("ix_slack_messages_thread_ts", "slack_messages", ["thread_ts"])
    op.create_index("ix_slack_messages_user_id", "slack_messages", ["user_id"])
    op.create_index("ix_slack_messages_ts_dt", "slack_messages", ["ts_dt"])
    op.create_index("ix_slack_messages_subtype", "slack_messages", ["subtype"])

    op.create_table(
        "slack_reactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("channel_id", sa.String(length=32), nullable=False),
        sa.Column("message_ts", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("reacted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("channel_id", "message_ts", "user_id", "name", name="uq_slack_reactions_natural"),
    )
    op.create_index("ix_slack_reactions_msg", "slack_reactions", ["channel_id", "message_ts"])

    op.create_table(
        "slack_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("file_id", sa.String(length=32), nullable=False),
        sa.Column("channel_id", sa.String(length=32)),
        sa.Column("message_ts", sa.String(length=32)),
        sa.Column("user_id", sa.String(length=32)),
        sa.Column("name", sa.String(length=255)),
        sa.Column("title", sa.String(length=255)),
        sa.Column("mimetype", sa.String(length=128)),
        sa.Column("filetype", sa.String(length=32)),
        sa.Column("size", sa.Integer()),
        sa.Column("url_private", sa.Text()),
        sa.Column("url_private_download", sa.Text()),
        sa.Column("thumb_url", sa.Text()),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at_source", sa.DateTime(timezone=True)),
        sa.Column("raw_payload", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("file_id", name="uq_slack_files_file_id"),
    )
    op.create_index("ix_slack_files_channel_id", "slack_files", ["channel_id"])
    op.create_index("ix_slack_files_message", "slack_files", ["channel_id", "message_ts"])
    op.create_index("ix_slack_files_filetype", "slack_files", ["filetype"])

    op.create_table(
        "slack_activity_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("channel_id", sa.String(length=32), nullable=False),
        sa.Column("channel_name", sa.String(length=128)),
        sa.Column("message_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unique_users", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reaction_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("thread_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reply_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("file_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("peak_hour", sa.Integer()),
        sa.Column("hour_histogram", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("top_users_json", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("business_date", "channel_id", name="uq_slack_activity_daily_date_channel"),
    )
    op.create_index("ix_slack_activity_daily_date", "slack_activity_daily", ["business_date"])


def downgrade() -> None:
    op.drop_index("ix_slack_activity_daily_date", table_name="slack_activity_daily")
    op.drop_table("slack_activity_daily")

    op.drop_index("ix_slack_files_filetype", table_name="slack_files")
    op.drop_index("ix_slack_files_message", table_name="slack_files")
    op.drop_index("ix_slack_files_channel_id", table_name="slack_files")
    op.drop_table("slack_files")

    op.drop_index("ix_slack_reactions_msg", table_name="slack_reactions")
    op.drop_table("slack_reactions")

    op.drop_index("ix_slack_messages_subtype", table_name="slack_messages")
    op.drop_index("ix_slack_messages_ts_dt", table_name="slack_messages")
    op.drop_index("ix_slack_messages_user_id", table_name="slack_messages")
    op.drop_index("ix_slack_messages_thread_ts", table_name="slack_messages")
    op.drop_index("ix_slack_messages_channel_ts", table_name="slack_messages")
    op.drop_table("slack_messages")

    op.drop_index("ix_slack_users_is_deleted", table_name="slack_users")
    op.drop_index("ix_slack_users_email", table_name="slack_users")
    op.drop_index("ix_slack_users_user_id", table_name="slack_users")
    op.drop_table("slack_users")

    op.drop_index("ix_slack_channels_is_archived", table_name="slack_channels")
    op.drop_index("ix_slack_channels_name", table_name="slack_channels")
    op.drop_index("ix_slack_channels_channel_id", table_name="slack_channels")
    op.drop_table("slack_channels")
