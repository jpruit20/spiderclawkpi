"""add DECI decision framework tables

Revision ID: 20260412_0015
Revises: 20260412_0014
Create Date: 2026-04-12 12:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260412_0015"
down_revision = "20260412_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deci_team_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("role", sa.String(128), nullable=True),
        sa.Column("department", sa.String(64), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "deci_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("type", sa.String(32), nullable=False, server_default=sa.text("'project'")),
        sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'not_started'")),
        sa.Column("priority", sa.String(16), nullable=False, server_default=sa.text("'medium'")),
        sa.Column("department", sa.String(64), nullable=True),
        sa.Column("driver_id", sa.Integer(), sa.ForeignKey("deci_team_members.id"), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_deci_decisions_department", "deci_decisions", ["department"])

    op.create_table(
        "deci_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_id", sa.String(36), sa.ForeignKey("deci_decisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("deci_team_members.id"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("decision_id", "member_id", "role", name="uq_deci_assignment"),
    )
    op.create_index("ix_deci_assignments_decision_id", "deci_assignments", ["decision_id"])

    op.create_table(
        "deci_decision_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_id", sa.String(36), sa.ForeignKey("deci_decisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision_text", sa.Text(), nullable=False),
        sa.Column("made_by", sa.String(128), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_deci_decision_logs_decision_id", "deci_decision_logs", ["decision_id"])

    op.create_table(
        "deci_kpi_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_id", sa.String(36), sa.ForeignKey("deci_decisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kpi_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_deci_kpi_links_decision_id", "deci_kpi_links", ["decision_id"])


def downgrade() -> None:
    op.drop_table("deci_kpi_links")
    op.drop_table("deci_decision_logs")
    op.drop_table("deci_assignments")
    op.drop_table("deci_decisions")
    op.drop_table("deci_team_members")
