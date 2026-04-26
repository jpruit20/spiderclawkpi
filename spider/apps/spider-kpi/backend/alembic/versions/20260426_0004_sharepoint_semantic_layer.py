"""SharePoint semantic layer: classification + BOM + canonical sources

Adds the columns + tables that turn the SharePoint mirror from "just a
file feed" into a queryable intelligence layer:

- ``sharepoint_documents.archive_status`` — active | archived | deprecated
  (heuristic from path + folder name patterns; ``Archive``/``Archive CAD``
  folders, plus filenames containing ``old``/``deprecated`` markers)

- ``sharepoint_documents.semantic_type`` — bom | cbom | price_list |
  tech_pack | design_doc | cad | image | video | presentation | other.
  Lets the dashboard filter to "show me only the BOMs" or roll up COGS.

- ``sharepoint_documents.parsed_metadata`` — JSONB. Filename parsing
  result: sku_code (e.g. ATL-SPG-00163), revision_letter (A/B/C/M),
  doc_date (YYYYMMDD), assembly_name. So the dashboard can group all
  ``Main Assembly`` revs and pick the latest non-archived one.

- ``sharepoint_bom_lines`` — extracted BOM rows from Excel parses.
  One row per part: file_id, line_no, part_number, description,
  vendor_name, qty, unit, unit_cost_usd, total_cost_usd, currency_raw,
  raw_row_json. This is the COGS roll-up substrate.

- ``sharepoint_canonical_sources`` — per (data_type, product, division)
  the override of which file is the source of truth. Auto-chosen by
  default (newest non-archived BOM); a human override always wins.
  Tracks who/when/why.

- ``sharepoint_extraction_runs`` — append-only log of "we tried to
  extract from this file"; status, lines_extracted, error_message,
  parser_version. Lets us re-extract a single failed file and trace
  parser regressions.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260426_0004"
down_revision = "20260426_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Classification columns on the doc table ───────────────────────
    op.execute(
        """
        ALTER TABLE sharepoint_documents
            ADD COLUMN IF NOT EXISTS archive_status varchar(16),
            ADD COLUMN IF NOT EXISTS semantic_type  varchar(32),
            ADD COLUMN IF NOT EXISTS parsed_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            ADD COLUMN IF NOT EXISTS classified_at  timestamptz
        """
    )
    op.create_index(
        "ix_sharepoint_documents_archive_status",
        "sharepoint_documents",
        ["archive_status"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_sharepoint_documents_semantic_type",
        "sharepoint_documents",
        ["semantic_type"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_sharepoint_documents_archive_semantic_div",
        "sharepoint_documents",
        ["archive_status", "semantic_type", "dashboard_division"],
        if_not_exists=True,
    )

    # ── BOM extracted lines ──────────────────────────────────────────
    op.create_table(
        "sharepoint_bom_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("sharepoint_documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("line_no", sa.Integer()),
        sa.Column("part_number", sa.String(255), index=True),
        sa.Column("description", sa.Text()),
        sa.Column("vendor_name", sa.String(255), index=True),
        sa.Column("qty", sa.Numeric(14, 4)),
        sa.Column("unit", sa.String(32)),
        sa.Column("unit_cost_usd", sa.Numeric(14, 4)),
        sa.Column("total_cost_usd", sa.Numeric(14, 4)),
        sa.Column("currency_raw", sa.String(8)),
        sa.Column("raw_row_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_sharepoint_bom_lines_doc_part", "sharepoint_bom_lines", ["document_id", "part_number"])

    # ── Canonical source overrides ───────────────────────────────────
    # data_type examples: cogs, bom, vendor_list, design_spec, drawing
    op.create_table(
        "sharepoint_canonical_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("data_type", sa.String(32), nullable=False, index=True),
        sa.Column("spider_product", sa.String(64), nullable=True, index=True),
        sa.Column("dashboard_division", sa.String(32), nullable=True, index=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("sharepoint_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("auto_chosen", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("override_user", sa.String(255)),
        sa.Column("override_note", sa.Text()),
        sa.Column("override_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("data_type", "spider_product", "dashboard_division", name="uq_canonical_source_scope"),
    )

    # ── Extraction run log ───────────────────────────────────────────
    op.create_table(
        "sharepoint_extraction_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("sharepoint_documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("kind", sa.String(32), nullable=False),  # bom | classify | vendor | ...
        sa.Column("status", sa.String(16), nullable=False),  # success | failed | skipped
        sa.Column("parser_version", sa.String(32)),
        sa.Column("lines_extracted", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_message", sa.Text()),
        sa.Column("ran_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index(
        "ix_sharepoint_extraction_runs_doc_kind_ran",
        "sharepoint_extraction_runs",
        ["document_id", "kind", "ran_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_sharepoint_extraction_runs_doc_kind_ran", table_name="sharepoint_extraction_runs")
    op.drop_table("sharepoint_extraction_runs")
    op.drop_table("sharepoint_canonical_sources")
    op.drop_index("ix_sharepoint_bom_lines_doc_part", table_name="sharepoint_bom_lines")
    op.drop_table("sharepoint_bom_lines")
    op.drop_index("ix_sharepoint_documents_archive_semantic_div", table_name="sharepoint_documents")
    op.drop_index("ix_sharepoint_documents_semantic_type", table_name="sharepoint_documents")
    op.drop_index("ix_sharepoint_documents_archive_status", table_name="sharepoint_documents")
    op.execute(
        """
        ALTER TABLE sharepoint_documents
            DROP COLUMN IF EXISTS classified_at,
            DROP COLUMN IF EXISTS parsed_metadata,
            DROP COLUMN IF EXISTS semantic_type,
            DROP COLUMN IF EXISTS archive_status
        """
    )
