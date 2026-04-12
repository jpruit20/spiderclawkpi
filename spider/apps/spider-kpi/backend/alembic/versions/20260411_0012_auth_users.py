"""add auth_users table for domain-restricted dashboard accounts

Revision ID: 20260411_0012
Revises: 20260411_0011
Create Date: 2026-04-11 20:55:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260411_0012"
down_revision = "20260411_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("email_domain", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("email", name="uq_auth_users_email"),
    )
    op.create_index("ix_auth_users_email", "auth_users", ["email"], unique=True)
    op.create_index("ix_auth_users_email_domain", "auth_users", ["email_domain"])
    op.create_index("ix_auth_users_is_active", "auth_users", ["is_active"])
    op.create_index("ix_auth_users_is_admin", "auth_users", ["is_admin"])
    op.create_index("ix_auth_users_last_login_at", "auth_users", ["last_login_at"])


def downgrade() -> None:
    op.drop_index("ix_auth_users_last_login_at", table_name="auth_users")
    op.drop_index("ix_auth_users_is_admin", table_name="auth_users")
    op.drop_index("ix_auth_users_is_active", table_name="auth_users")
    op.drop_index("ix_auth_users_email_domain", table_name="auth_users")
    op.drop_index("ix_auth_users_email", table_name="auth_users")
    op.drop_table("auth_users")
