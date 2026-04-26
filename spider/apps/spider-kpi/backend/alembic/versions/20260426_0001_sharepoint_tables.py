"""Add Microsoft tenants + SharePoint mirror tables.

Revision ID: 20260426_0001
Revises: 20260425_0009
Create Date: 2026-04-26

Multi-tenant by design: ``microsoft_tenants`` lets us register the AMW
tenant today and the future Spider Grills tenant later without
schema changes. The Azure AD app is multi-tenant on the platform side
so we only have one CLIENT_ID/CLIENT_SECRET pair regardless of how
many tenants we onboard.

``sharepoint_sites`` is the allowlist + the mirror of each granted
site's metadata. Joseph adds rows here for each AMW SharePoint card
the dashboard is allowed to read. The ``Sites.Selected`` permission
on the Azure AD app means Microsoft will refuse to return data for
any site NOT in this list and ALSO not granted via
``POST /sites/{id}/permissions`` — belt and suspenders.

``sharepoint_documents`` and ``sharepoint_list_items`` are the
content tables. Both denormalize ``spider_product`` and
``dashboard_division`` so common cross-tenant cross-product queries
don't need multi-table joins.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260426_0001"
down_revision = "20260425_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Tenants ───────────────────────────────────────────────────────
    op.create_table(
        "microsoft_tenants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("primary_domain", sa.String(255)),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )

    # ── Sites (allowlist + metadata mirror) ───────────────────────────
    op.create_table(
        "sharepoint_sites",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Tenant scope
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        # Graph site identifier — looks like "alignmachineworks.sharepoint.com,GUID,GUID"
        sa.Column("graph_site_id", sa.String(256), nullable=True, unique=True, index=True),
        # The path slug we resolve to graph_site_id, e.g. "ATL-SPG-00163-SpiderHuntsman2"
        sa.Column("site_path", sa.String(255), nullable=False),
        sa.Column("hostname", sa.String(128), nullable=False, server_default="alignmachineworks.sharepoint.com"),
        sa.Column("display_name", sa.String(255)),
        sa.Column("web_url", sa.String(512)),
        # Dashboard wiring — what does this card represent?
        sa.Column("spider_product", sa.String(64), nullable=True, index=True),  # Huntsman, Giant Huntsman, Webcraft, Giant Webcraft, Venom, Spider-wide
        sa.Column("default_division", sa.String(32), nullable=True, index=True),  # pe | operations | manufacturing | spider-wide
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("granted_at", sa.DateTime(timezone=True)),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), index=True),
        sa.Column("last_sync_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("tenant_id", "site_path", name="uq_sharepoint_sites_tenant_path"),
    )

    # ── Documents (files + folders) ───────────────────────────────────
    op.create_table(
        "sharepoint_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("graph_site_id", sa.String(256), nullable=False, index=True),
        sa.Column("graph_drive_id", sa.String(256), nullable=False),
        sa.Column("graph_item_id", sa.String(256), nullable=False),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("path", sa.String(2048), nullable=False, index=True),
        sa.Column("is_folder", sa.Boolean(), nullable=False, server_default=sa.false()),
        # Folder ancestry — denormalized for queries like "all docs under Engineering"
        sa.Column("top_level_folder", sa.String(255), index=True),  # Engineering / General / Production and QC / Project Management
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("mime_type", sa.String(128)),
        sa.Column("web_url", sa.String(2048)),
        sa.Column("created_by_email", sa.String(255)),
        sa.Column("created_at_remote", sa.DateTime(timezone=True)),
        sa.Column("modified_by_email", sa.String(255), index=True),
        sa.Column("modified_at_remote", sa.DateTime(timezone=True), index=True),
        # Dashboard wiring (denormalized from sharepoint_sites)
        sa.Column("spider_product", sa.String(64), index=True),
        sa.Column("dashboard_division", sa.String(32), index=True),
        # Raw blob for fields we haven't promoted yet
        sa.Column("raw_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("graph_drive_id", "graph_item_id", name="uq_sharepoint_documents_drive_item"),
    )
    op.create_index(
        "ix_sharepoint_documents_modified_div",
        "sharepoint_documents",
        ["dashboard_division", "modified_at_remote"],
    )

    # ── List items (structured data) ──────────────────────────────────
    op.create_table(
        "sharepoint_list_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("graph_site_id", sa.String(256), nullable=False, index=True),
        sa.Column("graph_list_id", sa.String(256), nullable=False),
        sa.Column("graph_list_name", sa.String(255), index=True),
        sa.Column("graph_item_id", sa.String(256), nullable=False),
        sa.Column("title", sa.String(1024)),
        sa.Column("created_by_email", sa.String(255)),
        sa.Column("created_at_remote", sa.DateTime(timezone=True)),
        sa.Column("modified_by_email", sa.String(255)),
        sa.Column("modified_at_remote", sa.DateTime(timezone=True), index=True),
        sa.Column("web_url", sa.String(2048)),
        sa.Column("fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("spider_product", sa.String(64), index=True),
        sa.Column("dashboard_division", sa.String(32), index=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("graph_list_id", "graph_item_id", name="uq_sharepoint_list_items_list_item"),
    )


def downgrade() -> None:
    op.drop_index("ix_sharepoint_documents_modified_div", table_name="sharepoint_documents")
    op.drop_table("sharepoint_list_items")
    op.drop_table("sharepoint_documents")
    op.drop_table("sharepoint_sites")
    op.drop_table("microsoft_tenants")
