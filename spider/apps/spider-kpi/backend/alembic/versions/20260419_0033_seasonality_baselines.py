"""Seasonality baselines — per-metric, per-day-of-year historical distributions

Revision ID: 20260419_0033
Revises: 20260419_0032
Create Date: 2026-04-19 18:15:00.000000-04:00

Phase 1 of the "company lore" initiative (Joseph 2026-04-19). For every
metric we care about (revenue, orders, sessions, ad_spend, active_devices,
session_count, tickets_created, etc.) we pre-compute the historical
distribution per day-of-year: p10 / p25 / p50 / p75 / p90 plus mean +
stddev + the actual year→value samples for transparency.

This unlocks:
  * "Running hot/cold" badges on every KPI tile vs seasonal baseline
  * Shaded p25-p75 baseline band overlay on any time-series chart
  * Percentile-rank callouts ("revenue this week is in the 87th percentile
    of the past 2 years of same-week data")

Grilling is extremely seasonal for Spider Grills (Memorial Day through
July 4 is 3x winter weeks) so anchoring interpretation to seasonal
baseline — not just week-over-week deltas — is the single biggest
improvement in how the dashboard reads.

The table is materialized (not computed on demand) because:
  * Queries are per-chart-per-date-range and need to be instant
  * Source data is daily rollups, so nightly refresh is trivial
  * Versioning + audit is easier on materialized rows

Unique constraint on (metric_name, day_of_year) — the canonical
seasonality axis. We don't index on year because the table captures
all historical years for each (metric, DoY) in the year_samples_json
column. One row per metric per DoY = (N_metrics × 366) rows total;
at the start that's ~3000 rows, tiny.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "20260419_0033"
down_revision = "20260419_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seasonality_baselines",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Canonical metric name — stable identifier used by API + frontend.
        # Examples: 'revenue', 'orders', 'sessions', 'ad_spend',
        # 'conversion_rate', 'active_devices', 'session_count',
        # 'tickets_created'.
        sa.Column("metric_name", sa.String(length=64), nullable=False),
        # Source table.column this baseline was derived from, e.g.
        # 'kpi_daily.revenue'. Useful for debugging and for
        # re-materializing after source-table changes.
        sa.Column("metric_source", sa.String(length=128), nullable=False),
        # Seasonality axis. day_of_year is 1-366 (leap years get day 366).
        sa.Column("day_of_year", sa.Integer(), nullable=False),
        sa.Column("iso_week", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),

        # Sample stats.
        sa.Column("year_count", sa.Integer(), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("p10", sa.Float(), nullable=True),
        sa.Column("p25", sa.Float(), nullable=True),
        sa.Column("p50", sa.Float(), nullable=True),  # median
        sa.Column("p75", sa.Float(), nullable=True),
        sa.Column("p90", sa.Float(), nullable=True),
        sa.Column("mean", sa.Float(), nullable=True),
        sa.Column("stddev", sa.Float(), nullable=True),

        # Transparency: {"2024": 45123.0, "2025": 52000.0}. Lets the
        # frontend show "based on 2 years of data (2024-2025)" and lets
        # us debug anomalous baselines by inspecting the inputs.
        sa.Column("year_samples_json", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),

        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.UniqueConstraint("metric_name", "day_of_year", name="uq_seasonality_baselines_metric_doy"),
    )
    op.create_index(
        "ix_seasonality_baselines_metric_doy",
        "seasonality_baselines",
        ["metric_name", "day_of_year"],
    )


def downgrade() -> None:
    op.drop_index("ix_seasonality_baselines_metric_doy", table_name="seasonality_baselines")
    op.drop_table("seasonality_baselines")
