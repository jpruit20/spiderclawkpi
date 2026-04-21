"""AI feedback + self-grade — close the loop on AI-generated artifacts.

Revision ID: 20260424_0001
Revises: 20260423_0001
Create Date: 2026-04-24

Adds two tables that capture whether the dashboard's AI outputs were
actually useful:

* ``ai_feedback``     — polymorphic one-reaction-per-(user,artifact) table.
                        Artifacts: ai_insight, deci_draft, issue_signal,
                        firmware_verdict. Reactions: acted_on, already_knew,
                        wrong, ignore.
* ``ai_self_grade``   — weekly Opus pass. Reads last 7d of insights joined
                        to ai_feedback + current outcomes; writes precision
                        per source, patterns of rejection, and a
                        ``prompt_delta`` suggestion for the insight engine's
                        system prompt. ``approved_at`` is set only after
                        Joseph explicitly approves — auto-apply is off so
                        Opus can't train itself on its own preferences.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260424_0001"
down_revision = "20260423_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_feedback",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_email", sa.String(320), nullable=False, index=True),
        sa.Column("artifact_type", sa.String(40), nullable=False),
        sa.Column("artifact_id", sa.String(80), nullable=False),
        sa.Column("reaction", sa.String(20), nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("user_email", "artifact_type", "artifact_id", name="uq_ai_feedback_user_artifact"),
    )
    op.create_index("ix_ai_feedback_artifact", "ai_feedback", ["artifact_type", "artifact_id"])
    op.create_index("ix_ai_feedback_reaction_created", "ai_feedback", ["reaction", "created_at"])

    op.create_table(
        "ai_self_grade",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, index=True),
        sa.Column("window_days", sa.Integer, nullable=False, server_default="7"),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("artifacts_scored", sa.Integer, nullable=False, server_default="0"),
        sa.Column("feedback_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("precision_by_source", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("rejection_themes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("overall_summary", sa.Text, nullable=True),
        sa.Column("prompt_delta", sa.Text, nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(320), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("usage_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("ai_self_grade")
    op.drop_index("ix_ai_feedback_reaction_created", table_name="ai_feedback")
    op.drop_index("ix_ai_feedback_artifact", table_name="ai_feedback")
    op.drop_table("ai_feedback")
