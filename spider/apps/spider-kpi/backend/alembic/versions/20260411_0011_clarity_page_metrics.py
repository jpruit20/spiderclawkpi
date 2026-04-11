"""add clarity_page_metrics table for UX friction analytics

Revision ID: 20260411_0011
Revises: 20260410_0010
Create Date: 2026-04-11 00:11:00
"""

from alembic import op
import sqlalchemy as sa

revision = "20260411_0011"
down_revision = "20260410_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clarity_page_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("page_path", sa.String(length=512), nullable=True),
        sa.Column("page_type", sa.String(length=64), nullable=True),
        sa.Column("sessions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dead_clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dead_click_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("rage_clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rage_click_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("quick_backs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quick_back_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("script_errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("script_error_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("excessive_scroll", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("friction_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("page_path", "snapshot_date", name="uq_clarity_page_metrics_path_date"),
    )
    op.create_index("ix_clarity_page_metrics_snapshot_date", "clarity_page_metrics", ["snapshot_date"])
    op.create_index("ix_clarity_page_metrics_page_type", "clarity_page_metrics", ["page_type"])
    op.create_index("ix_clarity_page_metrics_friction_score", "clarity_page_metrics", ["friction_score"])


def downgrade() -> None:
    op.drop_index("ix_clarity_page_metrics_friction_score", table_name="clarity_page_metrics")
    op.drop_index("ix_clarity_page_metrics_page_type", table_name="clarity_page_metrics")
    op.drop_index("ix_clarity_page_metrics_snapshot_date", table_name="clarity_page_metrics")
    op.drop_table("clarity_page_metrics")
