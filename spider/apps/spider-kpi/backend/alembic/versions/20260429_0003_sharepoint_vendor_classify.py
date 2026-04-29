"""SharePoint vendor-workspace classification columns.

Two new columns on ``sharepoint_documents`` to support content-based
filtering of Kienco / Qifei / future vendor sites where the
site-level ``spider_product`` allowlist is NULL (mixed-content):

  * ``spider_relevant`` — boolean, true if a Spider product, SKU, or
    project tag is detected in the filename or path. NULL until
    the classifier has run on the row.
  * ``detected_doc_kind`` — short string tag for downstream cards:
    'qa' | 'freight_ocean' | 'freight_air' | 'inspection' |
    'invoice' | 'shipping' | NULL.

Indexed on (spider_relevant, detected_doc_kind) so the dashboard's
"vendor inbound" cards can pull recent Spider-relevant freight docs
across all vendor sites in one query without scanning the whole
12k+ document mirror.
"""
from alembic import op
import sqlalchemy as sa


revision = "20260429_0003"
down_revision = "20260429_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sharepoint_documents",
        sa.Column("spider_relevant", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "sharepoint_documents",
        sa.Column("detected_doc_kind", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_sharepoint_documents_spider_relevant_kind",
        "sharepoint_documents",
        ["spider_relevant", "detected_doc_kind"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sharepoint_documents_spider_relevant_kind",
        table_name="sharepoint_documents",
    )
    op.drop_column("sharepoint_documents", "detected_doc_kind")
    op.drop_column("sharepoint_documents", "spider_relevant")
