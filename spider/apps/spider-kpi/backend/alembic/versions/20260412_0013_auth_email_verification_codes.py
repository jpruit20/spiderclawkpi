"""add auth email verification challenges

Revision ID: 20260412_0013
Revises: 20260411_0012
Create Date: 2026-04-12 07:58:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260412_0013"
down_revision = "20260411_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'auth_verification_challenges',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('email_domain', sa.String(length=255), nullable=False),
        sa.Column('code_hash', sa.String(length=128), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_auth_verification_challenges_email', 'auth_verification_challenges', ['email'])
    op.create_index('ix_auth_verification_challenges_email_domain', 'auth_verification_challenges', ['email_domain'])
    op.create_index('ix_auth_verification_challenges_expires_at', 'auth_verification_challenges', ['expires_at'])
    op.create_index('ix_auth_verification_challenges_consumed_at', 'auth_verification_challenges', ['consumed_at'])


def downgrade() -> None:
    op.drop_index('ix_auth_verification_challenges_consumed_at', table_name='auth_verification_challenges')
    op.drop_index('ix_auth_verification_challenges_expires_at', table_name='auth_verification_challenges')
    op.drop_index('ix_auth_verification_challenges_email_domain', table_name='auth_verification_challenges')
    op.drop_index('ix_auth_verification_challenges_email', table_name='auth_verification_challenges')
    op.drop_table('auth_verification_challenges')
