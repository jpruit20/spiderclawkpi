"""Deep analysis layer: file content + AI analysis + product synthesis

Three new tables that replace the previous "list of file links" feel
with actual analysis:

- ``sharepoint_file_content`` — Cached extracted text/structure per
  document. Excel sheets + per-sheet sample rows, PDF text, Word text,
  PowerPoint text. Hash + extracted_at so we can cheaply detect
  modifications without re-downloading.

- ``sharepoint_file_analysis`` — Claude's structured findings per
  document. ``purpose`` (one-sentence), ``key_facts`` (list of typed
  findings: cost / part / vendor / dimension / decision / revision /
  date), ``related_part_numbers``, ``related_vendors``, ``cost_data``,
  ``model_used``, ``analyzed_at``. Lets the dashboard cite specific
  facts back to specific files.

- ``sharepoint_product_intelligence`` — Per-product cross-file
  synthesis. ``narrative_md`` is what shows at the top of the
  intelligence card; ``cogs_summary``, ``design_status``,
  ``vendor_summary``, ``data_quality_issues`` are typed sub-payloads.
  ``citations`` is a list of (claim, document_id) so the UI links
  every claim to its source file.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260426_0005"
down_revision = "20260426_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sharepoint_file_content",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("sharepoint_documents.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        # The actual extracted content.
        # text_content: Word/PDF/PPT plain text (truncated)
        # structure_json: Excel sheet layouts, list-of-headers, sample rows
        sa.Column("text_content", sa.Text()),
        sa.Column("structure_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        # Cache key: bytes hash and source modified_at so we re-extract
        # on real modifications without thrashing on row touches.
        sa.Column("content_sha256", sa.String(64)),
        sa.Column("source_modified_at", sa.DateTime(timezone=True)),
        sa.Column("byte_size", sa.BigInteger()),
        sa.Column("extractor_version", sa.String(32), nullable=False, server_default="content-v1"),
        sa.Column("extraction_status", sa.String(16), nullable=False, server_default="ok"),
        sa.Column("extraction_error", sa.Text()),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )

    op.create_table(
        "sharepoint_file_analysis",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("sharepoint_documents.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("purpose", sa.Text()),
        sa.Column("key_facts", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("related_part_numbers", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("related_vendors", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("cost_data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("design_data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("decisions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("data_quality_flags", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("model_used", sa.String(64)),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("analyzer_version", sa.String(32), nullable=False, server_default="analysis-v1"),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )

    op.create_table(
        "sharepoint_product_intelligence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("spider_product", sa.String(64), nullable=False),
        sa.Column("dashboard_division", sa.String(32)),
        sa.Column("narrative_md", sa.Text()),
        sa.Column("cogs_summary", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("design_status", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("vendor_summary", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("data_quality_issues", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("citations", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("files_analyzed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("model_used", sa.String(64)),
        sa.Column("synthesizer_version", sa.String(32), nullable=False, server_default="synth-v1"),
        sa.Column("synthesized_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("spider_product", "dashboard_division", name="uq_sp_product_intel_scope"),
    )


def downgrade() -> None:
    op.drop_table("sharepoint_product_intelligence")
    op.drop_table("sharepoint_file_analysis")
    op.drop_table("sharepoint_file_content")
