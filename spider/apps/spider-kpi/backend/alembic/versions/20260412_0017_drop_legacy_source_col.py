"""Drop legacy source column from social_mentions

The initial schema (0001) created social_mentions with a NOT NULL 'source'
column.  Migration 0010 added 'platform' to replace it but never dropped
'source'.  Any INSERT that uses the new model (which has no 'source' attr)
will hit a NOT NULL violation on the legacy column.

Also drops other legacy columns (severity, topic, product) from the old
schema that are no longer in the model.

Revision ID: 20260412_0017
Revises: 20260412_0016
Create Date: 2026-04-12 14:00:00.000000+00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "20260412_0017"
down_revision = "20260412_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Use raw SQL with IF EXISTS to avoid poisoning the PostgreSQL transaction
    # (try/except on op.drop_index aborts the PG transaction even if Python catches it)
    for col_name in ("source", "severity", "topic", "product"):
        col_exists = conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'social_mentions' AND column_name = :col)"
            ),
            {"col": col_name},
        ).scalar()
        if col_exists:
            # DROP INDEX IF EXISTS is safe — won't error or abort transaction
            conn.execute(sa.text(
                f'DROP INDEX IF EXISTS "ix_social_mentions_{col_name}"'
            ))
            op.drop_column("social_mentions", col_name)


def downgrade() -> None:
    conn = op.get_bind()

    for col_name, col_type, default in [
        ("source", sa.String(64), "reddit"),
        ("severity", sa.String(32), "info"),
        ("topic", sa.String(128), None),
        ("product", sa.String(128), None),
    ]:
        col_exists = conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'social_mentions' AND column_name = :col)"
            ),
            {"col": col_name},
        ).scalar()
        if not col_exists:
            nullable = default is None
            kwargs = {}
            if default is not None:
                kwargs["server_default"] = default
            op.add_column(
                "social_mentions",
                sa.Column(col_name, col_type, nullable=nullable, **kwargs),
            )
