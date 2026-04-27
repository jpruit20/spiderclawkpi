"""kpi_targets: add division + owner_email columns

Joseph wants per-division KPI ownership:
- Joseph (joseph@spidergrills.com) can edit any division's targets
- Each division lead owns their own division's targets:
    bailey@spidergrills.com → marketing
    jeremiah@spidergrills.com → cx (customer-experience)
    conor@spidergrills.com → operations
    kyle@alignmachineworks.com → pe (product-engineering)
    david@alignmachineworks.com → manufacturing (production-manufacturing)

division=NULL means a global target (Command Center scope, Joseph-only).
owner_email is the email of the person who created/last-edited the row,
used for audit + UI badges.
"""
from alembic import op
import sqlalchemy as sa


revision = "20260427_0003"
down_revision = "20260427_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE kpi_targets
            ADD COLUMN IF NOT EXISTS division varchar(32),
            ADD COLUMN IF NOT EXISTS owner_email varchar(255)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_kpi_targets_division ON kpi_targets (division)
    """)
    # Backfill owner_email from created_by where present so existing
    # rows have a non-null audit field.
    op.execute("""
        UPDATE kpi_targets
        SET owner_email = created_by
        WHERE owner_email IS NULL AND created_by IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_kpi_targets_division")
    op.execute("ALTER TABLE kpi_targets DROP COLUMN IF EXISTS owner_email, DROP COLUMN IF EXISTS division")
