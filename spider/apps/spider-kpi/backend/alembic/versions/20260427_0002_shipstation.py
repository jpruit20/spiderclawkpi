"""ShipStation: stores + shipments mirror.

Mirrors only Spider Grills' configured stores (the operator's
``shipstation_spider_store_ids`` allowlist). The connector filters
on ``storeId`` server-side AND we only persist allow-listed rows
client-side so a misconfigured allowlist can't leak rows from the
other companies' stores.

Shipping cost (``shipment_cost`` + ``insurance_cost``) is what feeds
back into the gross-profit calculator — it's added to applied COGS
so the margin reflects what we actually paid to deliver the order.
``order_number`` is the customer-facing order id which matches the
Shopify ``name`` field, used to attribute shipping back per order.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260427_0002"
down_revision = "20260427_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shipstation_stores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ss_store_id", sa.Integer(), nullable=False, unique=True, index=True),
        sa.Column("store_name", sa.String(255), nullable=False),
        sa.Column("marketplace", sa.String(64)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("included_in_spider", sa.Boolean(), nullable=False, server_default=sa.false(), index=True),
        sa.Column("first_shipment_at", sa.DateTime(timezone=True)),
        sa.Column("last_shipment_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )

    op.create_table(
        "shipstation_shipments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ss_shipment_id", sa.BigInteger(), nullable=False, unique=True, index=True),
        sa.Column("ss_order_id", sa.BigInteger(), index=True),
        sa.Column("ss_order_number", sa.String(128), index=True),
        sa.Column("ss_store_id", sa.Integer(), nullable=False, index=True),
        sa.Column("customer_email", sa.String(255), index=True),
        # Costs in USD as reported by carrier — already in dollars on ShipStation v1.
        sa.Column("shipment_cost", sa.Numeric(10, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("insurance_cost", sa.Numeric(10, 4), nullable=False, server_default=sa.text("0")),
        # Carrier + service identifiers
        sa.Column("carrier_code", sa.String(64)),
        sa.Column("service_code", sa.String(64)),
        sa.Column("package_code", sa.String(64)),
        sa.Column("tracking_number", sa.String(255)),
        sa.Column("ship_date", sa.Date(), index=True),
        sa.Column("create_date", sa.DateTime(timezone=True), index=True),
        sa.Column("void_date", sa.DateTime(timezone=True)),
        sa.Column("voided", sa.Boolean(), nullable=False, server_default=sa.false()),
        # Weights are in ounces per ShipStation's WeightUnits.Ounces enum
        sa.Column("weight_oz", sa.Numeric(10, 3)),
        sa.Column("dimensions_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("warehouse_id", sa.Integer()),
        sa.Column("ship_to_state", sa.String(64)),
        sa.Column("ship_to_country", sa.String(8)),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_shipstation_shipments_ship_date_store", "shipstation_shipments", ["ship_date", "ss_store_id"])
    op.create_index("ix_shipstation_shipments_create_date_store", "shipstation_shipments", ["create_date", "ss_store_id"])


def downgrade() -> None:
    op.drop_index("ix_shipstation_shipments_create_date_store", table_name="shipstation_shipments")
    op.drop_index("ix_shipstation_shipments_ship_date_store", table_name="shipstation_shipments")
    op.drop_table("shipstation_shipments")
    op.drop_table("shipstation_stores")
