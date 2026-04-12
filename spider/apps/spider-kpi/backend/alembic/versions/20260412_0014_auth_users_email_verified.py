"""add email_verified column to auth_users

Revision ID: 20260412_0014
Revises: 20260412_0013
Create Date: 2026-04-12 10:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260412_0014"
down_revision = "20260412_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'auth_users',
        sa.Column('email_verified', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )
    op.create_index('ix_auth_users_email_verified', 'auth_users', ['email_verified'])
    # Rename code_hash → token_hash in verification challenges (wider tokens for links)
    op.alter_column(
        'auth_verification_challenges',
        'code_hash',
        new_column_name='token_hash',
    )
    # Add purpose column to distinguish signup-verify vs future reset-password
    op.add_column(
        'auth_verification_challenges',
        sa.Column('purpose', sa.String(length=32), nullable=False, server_default=sa.text("'verify_email'")),
    )


def downgrade() -> None:
    op.drop_column('auth_verification_challenges', 'purpose')
    op.alter_column(
        'auth_verification_challenges',
        'token_hash',
        new_column_name='code_hash',
    )
    op.drop_index('ix_auth_users_email_verified', table_name='auth_users')
    op.drop_column('auth_users', 'email_verified')
