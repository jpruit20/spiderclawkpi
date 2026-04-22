"""Partner product catalog + financial modeling fields on JIT subs.

Revision ID: 20260425_0005
Revises: 20260425_0004
Create Date: 2026-04-22

Adds:
  * ``partner_products`` — scraped upstream catalog (Jealous Devil
    today; future Royal Oak / Kingsford etc slot in under the same
    schema). Daily refresh keeps retail price in sync automatically.
  * ``charcoal_jit_subscriptions.partner_product_id`` — FK to the
    partner catalog so each subscription knows which specific SKU it
    maps to, and retail price flows through automatically.
  * ``charcoal_jit_subscriptions.margin_pct`` — Spider Grills' cut,
    default 10%, tunable per subscription.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260425_0005"
down_revision = "20260425_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "partner_products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("partner", sa.String(64), nullable=False),
        sa.Column("handle", sa.String(256), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("fuel_type", sa.String(16), nullable=True),
        sa.Column("bag_size_lb", sa.Integer(), nullable=True),
        sa.Column("retail_price_usd", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("source_url", sa.String(1024), nullable=True),
        sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "last_fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "raw_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("partner", "handle", name="uq_partner_products_partner_handle"),
    )
    op.create_index("ix_partner_products_partner", "partner_products", ["partner"])
    op.create_index("ix_partner_products_available", "partner_products", ["available"])

    op.add_column(
        "charcoal_jit_subscriptions",
        sa.Column(
            "partner_product_id",
            sa.Integer(),
            sa.ForeignKey("partner_products.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "charcoal_jit_subscriptions",
        sa.Column(
            "margin_pct",
            sa.Float(),
            nullable=False,
            server_default="10.0",
        ),
    )


def downgrade() -> None:
    op.drop_column("charcoal_jit_subscriptions", "margin_pct")
    op.drop_column("charcoal_jit_subscriptions", "partner_product_id")
    op.drop_index("ix_partner_products_available", table_name="partner_products")
    op.drop_index("ix_partner_products_partner", table_name="partner_products")
    op.drop_table("partner_products")
