"""Hotfix: add created_at + updated_at to sharepoint_documents + sharepoint_list_items

Both models inherit ``TimestampMixin`` (which declares created_at +
updated_at), but the original 0001 migration only added those columns
to ``microsoft_tenants`` and ``sharepoint_sites``. The ORM SELECT in
``GET /api/sharepoint/recent-changes`` therefore failed with
``UndefinedColumn: sharepoint_documents.created_at`` once the route
was hit on the Operations / Manufacturing pages.

Idempotent — uses ADD COLUMN IF NOT EXISTS so safe to re-run on
environments where someone already patched by hand.
"""
from alembic import op


revision = "20260426_0003"
down_revision = "20260426_0002"
branch_labels = None
depends_on = None


TABLES = ("sharepoint_documents", "sharepoint_list_items")


def upgrade() -> None:
    for tbl in TABLES:
        op.execute(
            f"""
            ALTER TABLE {tbl}
                ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT NOW(),
                ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT NOW()
            """
        )


def downgrade() -> None:
    for tbl in TABLES:
        op.execute(f"ALTER TABLE {tbl} DROP COLUMN IF EXISTS created_at, DROP COLUMN IF EXISTS updated_at")
