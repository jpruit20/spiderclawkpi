"""Add decision domains and enhance decisions

Revision ID: 20260412_0016_deci_domains
Revises: 20260412_0015
Create Date: 2026-04-12 12:00:00.000000+00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260412_0016"
down_revision = "20260412_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deci_domains",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(64), nullable=False, server_default="operations"),
        sa.Column("default_driver_id", sa.Integer(), nullable=True),
        sa.Column("default_executor_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("default_contributor_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("default_informed_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("escalation_owner_id", sa.Integer(), nullable=True),
        sa.Column("escalation_threshold_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_deci_domains_name"),
        sa.ForeignKeyConstraint(["default_driver_id"], ["deci_team_members.id"]),
        sa.ForeignKeyConstraint(["escalation_owner_id"], ["deci_team_members.id"]),
    )

    op.add_column("deci_decisions", sa.Column("domain_id", sa.Integer(), nullable=True))
    op.add_column("deci_decisions", sa.Column("escalation_status", sa.String(32), nullable=False, server_default="none"))
    op.add_column("deci_decisions", sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("deci_decisions", sa.Column("cross_functional", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("deci_decisions", sa.Column("due_date", sa.Date(), nullable=True))
    op.add_column("deci_decisions", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_deci_decisions_domain_id", "deci_decisions", ["domain_id"])
    op.create_foreign_key("fk_deci_decisions_domain_id", "deci_decisions", "deci_domains", ["domain_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_deci_decisions_domain_id", "deci_decisions", type_="foreignkey")
    op.drop_index("ix_deci_decisions_domain_id", "deci_decisions")
    op.drop_column("deci_decisions", "resolved_at")
    op.drop_column("deci_decisions", "due_date")
    op.drop_column("deci_decisions", "cross_functional")
    op.drop_column("deci_decisions", "escalated_at")
    op.drop_column("deci_decisions", "escalation_status")
    op.drop_column("deci_decisions", "domain_id")
    op.drop_table("deci_domains")
