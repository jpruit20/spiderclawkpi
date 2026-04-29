"""FedEx Web Services + Billing Online ingestion tables.

Three independent tables, sharing a common pattern (idempotent on a
natural key, raw_payload JSONB for full provenance, indexed on the
fields the dashboard queries):

  * ``fedex_freight_ltl_shipments`` — Giant Huntsman LTL shipments
    pulled from the Freight LTL API. These ship outside ShipStation
    so they're invisible to the existing cost-by-SKU pipeline; this
    table is what closes that gap.

  * ``fedex_invoice_charges`` — invoice line items from the FedEx
    Billing Online (FBO) scheduled CSV exports. The Web Services API
    doesn't expose invoice data (FedEx restricts it to EDI / Compatible
    Program partners), so the FBO email path is the only way. JOINs
    on tracking_number against ``shipstation_shipments`` to power the
    "ShipStation estimate vs FedEx invoiced" reconciliation card.

  * ``fedex_ground_eod_summaries`` — Ground End of Day Close API daily
    reports (when production-approved). Captures per-day shipment
    counts + summary cost figures for the parcel side of the account.

All three tables carry a Spider Grills tenancy filter via the
``is_spider`` boolean — populated at ingest by matching on
(a) a reference field convention agreed with operations, OR
(b) tracking_number ↔ shipstation_shipments fallback. Non-Spider
charges are still persisted (for visibility into what the umbrella
account does for other companies) but always filtered out of
dashboard queries via WHERE is_spider = true.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260429_0001"
down_revision = "20260427_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Freight LTL shipments ────────────────────────────────────────
    # Pulled from /rate/v1/freight/rates/quotes (rate quotes) and the
    # Freight tracking endpoint once we have shipped tracking numbers.
    # One row per FedEx Freight LTL shipment.
    op.create_table(
        "fedex_freight_ltl_shipments",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Natural key — FedEx assigns these as PRO numbers (Freight's
        # equivalent of a tracking number). Idempotent upserts use this.
        sa.Column("pro_number", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("tracking_number", sa.String(64), index=True),  # for cross-table joins
        sa.Column("ship_date", sa.Date(), index=True),
        sa.Column("delivery_date", sa.Date()),
        sa.Column("service_type", sa.String(64)),  # FEDEX_FREIGHT_PRIORITY, ECONOMY, etc
        # Spider tenancy — true if this shipment is for Spider Grills.
        # Determined at ingest by reference-field match or shipper-address match.
        sa.Column("is_spider", sa.Boolean(), nullable=False, server_default=sa.false(), index=True),
        sa.Column("reference_value", sa.String(128)),  # the value that triggered is_spider
        # Origin + destination
        sa.Column("shipper_account", sa.String(32)),
        sa.Column("shipper_postal_code", sa.String(16)),
        sa.Column("shipper_country", sa.String(8)),
        sa.Column("recipient_postal_code", sa.String(16)),
        sa.Column("recipient_state", sa.String(64)),
        sa.Column("recipient_country", sa.String(8)),
        # Freight-specific: weight, freight class, pieces, packaging
        sa.Column("total_weight_lb", sa.Numeric(10, 2)),
        sa.Column("freight_class", sa.String(16)),  # CLASS_125, CLASS_175, etc
        sa.Column("piece_count", sa.Integer()),
        sa.Column("packaging_type", sa.String(32)),  # CRATE, PALLET, BOX
        # Cost — split because Freight invoices break out the base rate
        # vs accessorial charges (lift gate, residential delivery, etc)
        sa.Column("base_charge_usd", sa.Numeric(10, 2)),
        sa.Column("accessorials_charge_usd", sa.Numeric(10, 2)),
        sa.Column("total_charge_usd", sa.Numeric(10, 2)),
        sa.Column("rate_type", sa.String(32)),  # ACCOUNT vs LIST — for cross-check
        # Bookkeeping
        sa.Column("status", sa.String(32)),  # IN_TRANSIT, DELIVERED, EXCEPTION
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index(
        "ix_fedex_ltl_shipments_spider_ship_date",
        "fedex_freight_ltl_shipments",
        ["is_spider", "ship_date"],
    )

    # ── Invoice charges (from FBO email exports) ─────────────────────
    # One row per (invoice_number, tracking_number, charge_type) tuple.
    # Surcharge rows (residential, fuel, dim-weight, etc) sit alongside
    # base-charge rows so totals reconcile, and the reconciliation card
    # can break down "why is this shipment $40 more than expected."
    op.create_table(
        "fedex_invoice_charges",
        sa.Column("id", sa.Integer(), primary_key=True),
        # FBO doesn't give us a single global natural key; build one
        # from invoice + tracking + charge ordinal.
        sa.Column("invoice_number", sa.String(64), nullable=False, index=True),
        sa.Column("invoice_date", sa.Date(), index=True),
        sa.Column("invoice_currency", sa.String(8), nullable=False, server_default=sa.text("'USD'")),
        sa.Column("tracking_number", sa.String(64), nullable=False, index=True),
        sa.Column("ship_date", sa.Date(), index=True),
        sa.Column("delivery_date", sa.Date()),
        # Spider tenancy filter — same convention as LTL above
        sa.Column("is_spider", sa.Boolean(), nullable=False, server_default=sa.false(), index=True),
        sa.Column("reference_value", sa.String(128)),
        # Carrier identifiers
        sa.Column("account_number", sa.String(32), index=True),
        sa.Column("service_type", sa.String(64)),
        sa.Column("carrier", sa.String(16), nullable=False, server_default=sa.text("'fedex'")),
        # Origin / destination postal codes + state for geographic reporting
        sa.Column("shipper_postal_code", sa.String(16)),
        sa.Column("recipient_postal_code", sa.String(16)),
        sa.Column("recipient_state", sa.String(64)),
        # The actual cost breakdown — multiple rows per shipment (one
        # per charge category) so we can aggregate or detail at will.
        sa.Column("charge_category", sa.String(64), nullable=False),  # BASE, FUEL, RESIDENTIAL, DIM_WEIGHT, GSR, PEAK, OTHER
        sa.Column("charge_description", sa.String(255)),  # human-readable description from the CSV
        sa.Column("charge_amount_usd", sa.Numeric(10, 2), nullable=False),
        # Weight + dimensional weight — both columns because FedEx bills
        # the higher of actual vs dim, and the delta is itself a metric
        sa.Column("billed_weight_lb", sa.Numeric(10, 2)),
        sa.Column("dim_weight_lb", sa.Numeric(10, 2)),
        sa.Column("actual_weight_lb", sa.Numeric(10, 2)),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint(
            "invoice_number", "tracking_number", "charge_category",
            name="uq_fedex_invoice_charges_invoice_tracking_category",
        ),
    )
    op.create_index(
        "ix_fedex_invoice_charges_spider_ship_date",
        "fedex_invoice_charges",
        ["is_spider", "ship_date"],
    )
    op.create_index(
        "ix_fedex_invoice_charges_tracking_for_join",
        "fedex_invoice_charges",
        ["tracking_number", "is_spider"],
    )

    # ── Ground EOD daily summaries ────────────────────────────────────
    # One row per (close_date, account_number). The Ground EOD Close
    # API returns a daily manifest summary; we store the headline
    # aggregates plus the full raw payload for any deep-dive needs.
    op.create_table(
        "fedex_ground_eod_summaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("close_date", sa.Date(), nullable=False, index=True),
        sa.Column("account_number", sa.String(32), nullable=False, index=True),
        sa.Column("is_spider", sa.Boolean(), nullable=False, server_default=sa.false(), index=True),
        # Headline aggregates parsed out of the close report
        sa.Column("total_shipments", sa.Integer()),
        sa.Column("total_pieces", sa.Integer()),
        sa.Column("total_weight_lb", sa.Numeric(12, 2)),
        sa.Column("total_charge_usd", sa.Numeric(12, 2)),
        sa.Column("manifest_id", sa.String(64)),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("close_date", "account_number", name="uq_fedex_ground_eod_close_account"),
    )

    # ── Rate quote audit trail (cross-check) ─────────────────────────
    # When we ask the Rates API "what should this label have cost",
    # we cache the answer with a TTL so we don't pound the API. Also
    # gives us a record over time of how list pricing drifted vs what
    # we actually paid.
    op.create_table(
        "fedex_rate_quotes",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Natural key: the shipment we're cross-checking + the rate type
        sa.Column("tracking_number", sa.String(64), nullable=False, index=True),
        sa.Column("rate_type", sa.String(32), nullable=False),  # ACCOUNT or LIST
        sa.Column("service_type", sa.String(64)),
        sa.Column("quoted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("quoted_charge_usd", sa.Numeric(10, 2)),
        sa.Column("currency", sa.String(8), nullable=False, server_default=sa.text("'USD'")),
        # The actuals we're comparing against (snapshotted at quote time
        # so historical analysis isn't poisoned by post-hoc edits)
        sa.Column("shipstation_charge_usd", sa.Numeric(10, 2)),
        sa.Column("delta_usd", sa.Numeric(10, 2)),  # quoted - shipstation; positive = list higher than what we paid (good)
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint("tracking_number", "rate_type", "service_type", name="uq_fedex_rate_quotes_tracking_type"),
    )
    op.create_index("ix_fedex_rate_quotes_quoted_at", "fedex_rate_quotes", ["quoted_at"])


def downgrade() -> None:
    op.drop_index("ix_fedex_rate_quotes_quoted_at", table_name="fedex_rate_quotes")
    op.drop_table("fedex_rate_quotes")
    op.drop_table("fedex_ground_eod_summaries")
    op.drop_index("ix_fedex_invoice_charges_tracking_for_join", table_name="fedex_invoice_charges")
    op.drop_index("ix_fedex_invoice_charges_spider_ship_date", table_name="fedex_invoice_charges")
    op.drop_table("fedex_invoice_charges")
    op.drop_index("ix_fedex_ltl_shipments_spider_ship_date", table_name="fedex_freight_ltl_shipments")
    op.drop_table("fedex_freight_ltl_shipments")
