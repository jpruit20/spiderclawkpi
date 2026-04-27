"""kpi_targets — operator-set targets per metric, with seasonal windows.

Joseph wants to track KPIs against targets that flex by season (grilling
season targets ≠ off-season targets). One row per (metric, period). The
active target for a metric on a given date is the row whose
[effective_start, effective_end) contains that date; if multiple match,
the narrowest window wins, then most-recently created.

``direction`` captures whether the metric should be at-or-above or
at-or-below the target (revenue is 'min'; tickets_created is 'max').
This drives the green/red coloring on the dashboard.
"""
from alembic import op
import sqlalchemy as sa


revision = "20260427_0001"
down_revision = "20260426_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kpi_targets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("metric_key", sa.String(64), nullable=False, index=True),
        sa.Column("target_value", sa.Numeric(14, 4), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False, server_default="min"),  # 'min' | 'max'
        sa.Column("effective_start", sa.Date(), nullable=True),
        sa.Column("effective_end", sa.Date(), nullable=True),
        sa.Column("season_label", sa.String(64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index(
        "ix_kpi_targets_metric_window",
        "kpi_targets",
        ["metric_key", "effective_start", "effective_end"],
    )


def downgrade() -> None:
    op.drop_index("ix_kpi_targets_metric_window", table_name="kpi_targets")
    op.drop_table("kpi_targets")
