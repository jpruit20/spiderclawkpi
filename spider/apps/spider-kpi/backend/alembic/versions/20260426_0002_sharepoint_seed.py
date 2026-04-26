"""Seed AMW tenant + 5 SharePoint sites in the allowlist.

Revision ID: 20260426_0002
Revises: 20260426_0001
Create Date: 2026-04-26

Joseph identified these 5 SharePoint sites for the day-1 allowlist
during the integration setup. Each site already had a per-site
``Sites.Selected`` grant applied via
``scripts/grant_sharepoint_sites.py`` so the dashboard's app-only
token can read them.

Spider product mapping established by inspecting site display names:

  ATL-SPG-00163-Spider Huntsman   → Huntsman
  ATL-SPG-00176-Giant Huntsman    → Giant Huntsman
  ATL-SPG-00177-Giant WebCraft    → Giant Webcraft
  ATL-SPG-00171-WebCraft          → Webcraft
  ATL-SPG-00116-Venom (slug:      → Venom (cross-product controller)
    RuggedOutdoors)

``default_division`` left null because each site's drive contains
mixed divisions (Engineering / Production and QC / Project Management
folders) — the connector classifies per-document via
``top_level_folder``, not per-site.
"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "20260426_0002"
down_revision = "20260426_0001"
branch_labels = None
depends_on = None


AMW_TENANT_ID = "2e9275cf-ffd9-4f18-abdc-c0ac8d85e26f"


SITES = [
    # (site_path, spider_product)
    ("ATL-SPG-00163-SpiderHuntsman2", "Huntsman"),
    ("ATL-SPG-00176-GiantHuntsman", "Giant Huntsman"),
    ("ATL-SPG-00177-GiantWebCraft2", "Giant Webcraft"),
    ("ATL-SPG-00171-WebCraft", "Webcraft"),
    ("RuggedOutdoors", "Venom"),
]


def upgrade() -> None:
    op.execute(sa.text("""
        INSERT INTO microsoft_tenants (tenant_id, display_name, primary_domain, enabled, notes, created_at, updated_at)
        VALUES (:tid, 'Align Machine Works, LLC', 'alignmachineworks.com', TRUE,
                'Seeded 2026-04-26. Spider Grills product cards. Sites.Selected grants applied via scripts/grant_sharepoint_sites.py.',
                NOW(), NOW())
        ON CONFLICT (tenant_id) DO NOTHING
    """).bindparams(tid=AMW_TENANT_ID))

    for site_path, product in SITES:
        op.execute(sa.text("""
            INSERT INTO sharepoint_sites (
                tenant_id, site_path, hostname, spider_product,
                default_division, enabled, granted_at, created_at, updated_at
            ) VALUES (
                :tid, :sp, 'alignmachineworks.sharepoint.com', :prod,
                NULL, TRUE, NOW(), NOW(), NOW()
            )
            ON CONFLICT (tenant_id, site_path) DO NOTHING
        """).bindparams(tid=AMW_TENANT_ID, sp=site_path, prod=product))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM sharepoint_sites WHERE tenant_id = :tid").bindparams(tid=AMW_TENANT_ID))
    op.execute(sa.text("DELETE FROM microsoft_tenants WHERE tenant_id = :tid").bindparams(tid=AMW_TENANT_ID))
