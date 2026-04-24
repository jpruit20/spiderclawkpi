"""Role + page_scope on auth_users.

Revision ID: 20260425_0004
Revises: 20260425_0003
Create Date: 2026-04-24

Adds two columns to support viewer-only accounts restricted to a subset
of dashboard routes:

* ``role`` — 'admin' / 'editor' / 'viewer'. Existing ``is_admin=True`` rows
  backfill to 'admin'; everyone else to 'editor' (they were already able
  to do anything). New signups default to 'viewer' unless the invited-
  users allowlist promotes them.
* ``page_scope`` — nullable JSONB array of route prefixes. ``null`` =
  unrestricted (see every page the role permits). A list like
  ``["/division/product-engineering"]`` restricts the account to routes
  whose pathname starts with any of those prefixes.

``role`` gets an index so the auth handlers can cheaply filter.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260425_0004"
down_revision = "20260425_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "auth_users",
        sa.Column("role", sa.String(32), nullable=False, server_default="viewer"),
    )
    op.add_column(
        "auth_users",
        sa.Column(
            "page_scope",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    # Backfill existing users: admins → 'admin', everyone else → 'editor'.
    # Nobody gets retroactively downgraded to 'viewer' — that's a new
    # category for external invitees.
    op.execute(
        "UPDATE auth_users SET role = CASE WHEN is_admin THEN 'admin' ELSE 'editor' END"
    )
    op.create_index("ix_auth_users_role", "auth_users", ["role"])


def downgrade() -> None:
    op.drop_index("ix_auth_users_role", table_name="auth_users")
    op.drop_column("auth_users", "page_scope")
    op.drop_column("auth_users", "role")
