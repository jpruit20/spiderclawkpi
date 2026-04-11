"""add social_mentions table for social listening

Revision ID: 20260410_0010
Revises: 20260410_0009
Create Date: 2026-04-10 23:30:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260410_0010"
down_revision = "20260410_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The social_mentions table may already exist with a simpler schema from an
    # earlier model definition.  We detect that and ALTER instead of CREATE.
    conn = op.get_bind()
    table_exists = conn.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'social_mentions')"
        )
    ).scalar()

    if table_exists:
        # Add missing columns to the existing table
        def _col_exists(name: str) -> bool:
            return conn.execute(
                sa.text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'social_mentions' AND column_name = :col)"
                ),
                {"col": name},
            ).scalar()

        if not _col_exists("platform"):
            op.add_column("social_mentions", sa.Column("platform", sa.String(length=32), nullable=False, server_default="reddit"))
        if not _col_exists("source_url"):
            op.add_column("social_mentions", sa.Column("source_url", sa.Text(), nullable=True))
        if not _col_exists("title"):
            op.add_column("social_mentions", sa.Column("title", sa.Text(), nullable=True))
        if not _col_exists("subreddit"):
            op.add_column("social_mentions", sa.Column("subreddit", sa.String(length=128), nullable=True))
        if not _col_exists("engagement_score"):
            op.add_column("social_mentions", sa.Column("engagement_score", sa.Integer(), nullable=False, server_default="0"))
        if not _col_exists("comment_count"):
            op.add_column("social_mentions", sa.Column("comment_count", sa.Integer(), nullable=False, server_default="0"))
        if not _col_exists("sentiment_score"):
            op.add_column("social_mentions", sa.Column("sentiment_score", sa.Float(), nullable=False, server_default="0.0"))
        if not _col_exists("classification"):
            op.add_column("social_mentions", sa.Column("classification", sa.String(length=64), nullable=False, server_default="unknown"))
        if not _col_exists("brand_mentioned"):
            op.add_column("social_mentions", sa.Column("brand_mentioned", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        if not _col_exists("product_mentioned"):
            op.add_column("social_mentions", sa.Column("product_mentioned", sa.String(length=128), nullable=True))
        if not _col_exists("competitor_mentioned"):
            op.add_column("social_mentions", sa.Column("competitor_mentioned", sa.String(length=128), nullable=True))
        if not _col_exists("trend_topic"):
            op.add_column("social_mentions", sa.Column("trend_topic", sa.String(length=128), nullable=True))
        if not _col_exists("relevance_score"):
            op.add_column("social_mentions", sa.Column("relevance_score", sa.Float(), nullable=False, server_default="0.0"))
        if not _col_exists("discovered_at"):
            op.add_column("social_mentions", sa.Column("discovered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))

        # Ensure the unique constraint exists
        try:
            op.create_unique_constraint("uq_social_mentions_platform_external_id", "social_mentions", ["platform", "external_id"])
        except Exception:
            pass  # constraint may already exist

    else:
        op.create_table(
            "social_mentions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("platform", sa.String(length=32), nullable=False),
            sa.Column("external_id", sa.String(length=255), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("title", sa.Text(), nullable=True),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("author", sa.String(length=128), nullable=True),
            sa.Column("subreddit", sa.String(length=128), nullable=True),
            sa.Column("engagement_score", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("comment_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sentiment", sa.String(length=16), nullable=False, server_default="neutral"),
            sa.Column("sentiment_score", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("classification", sa.String(length=64), nullable=False, server_default="unknown"),
            sa.Column("brand_mentioned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("product_mentioned", sa.String(length=128), nullable=True),
            sa.Column("competitor_mentioned", sa.String(length=128), nullable=True),
            sa.Column("trend_topic", sa.String(length=128), nullable=True),
            sa.Column("relevance_score", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("discovered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("platform", "external_id", name="uq_social_mentions_platform_external_id"),
        )
        op.create_index("ix_social_mentions_platform", "social_mentions", ["platform"])
        op.create_index("ix_social_mentions_classification", "social_mentions", ["classification"])
        op.create_index("ix_social_mentions_published_at", "social_mentions", ["published_at"])


def downgrade() -> None:
    # If the table was freshly created by this migration, drop it.
    # If it pre-existed and we only added columns, drop just those columns.
    conn = op.get_bind()

    has_platform = conn.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'social_mentions' AND column_name = 'platform')"
        )
    ).scalar()

    if has_platform:
        # Check if 'source' column also exists -- if so, this was the ALTER path
        has_source = conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'social_mentions' AND column_name = 'source')"
            )
        ).scalar()
        if has_source:
            # ALTER path: drop added columns
            for col in [
                "platform", "source_url", "title", "subreddit",
                "engagement_score", "comment_count", "sentiment_score",
                "classification", "brand_mentioned", "product_mentioned",
                "competitor_mentioned", "trend_topic", "relevance_score",
                "discovered_at",
            ]:
                try:
                    op.drop_column("social_mentions", col)
                except Exception:
                    pass
            try:
                op.drop_constraint("uq_social_mentions_platform_external_id", "social_mentions", type_="unique")
            except Exception:
                pass
        else:
            # Full CREATE path: drop the whole table
            op.drop_index("ix_social_mentions_published_at", table_name="social_mentions")
            op.drop_index("ix_social_mentions_classification", table_name="social_mentions")
            op.drop_index("ix_social_mentions_platform", table_name="social_mentions")
            op.drop_table("social_mentions")
