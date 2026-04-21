"""Cook behavior knowledge base — baselines, backtests, and Freshdesk
cook correlations.

Revision ID: 20260423_0001
Revises: 20260422_0001
Create Date: 2026-04-23

Adds three tables that power the time-aware cook state classifier and
the self-evaluating analytics layer:

* ``cook_behavior_baselines``   — learned p10/p50/p90 per target-temp
                                  band × firmware (ramp times, steady-
                                  state fan, stddev, cool-down rate,
                                  typical duration).
* ``cook_behavior_backtests``   — nightly self-evaluation: how well did
                                  the PRIOR baseline version predict
                                  last night's sessions?
* ``freshdesk_cook_correlations`` — per-ticket bridge to cook sessions
                                    within ±2h of ticket creation.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260423_0001"
down_revision = "20260422_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cook_behavior_baselines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("target_temp_band", sa.String(length=16), nullable=False),
        sa.Column("firmware_version", sa.String(length=64), nullable=True),
        sa.Column("baseline_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("ramp_time_p10", sa.Float()),
        sa.Column("ramp_time_p50", sa.Float()),
        sa.Column("ramp_time_p90", sa.Float()),
        sa.Column("steady_fan_p10", sa.Float()),
        sa.Column("steady_fan_p50", sa.Float()),
        sa.Column("steady_fan_p90", sa.Float()),
        sa.Column("steady_temp_stddev_p50", sa.Float()),
        sa.Column("steady_temp_stddev_p90", sa.Float()),
        sa.Column("cool_down_rate_p50", sa.Float()),
        sa.Column("typical_duration_p50", sa.Float()),
        sa.Column("computed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "target_temp_band", "firmware_version", "baseline_version",
            name="uq_cook_behavior_baselines_band_fw_ver",
        ),
    )
    op.create_index(
        "ix_cook_behavior_baselines_band",
        "cook_behavior_baselines",
        ["target_temp_band"],
    )

    op.create_table(
        "cook_behavior_backtests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("baseline_version", sa.Integer(), nullable=False),
        sa.Column("target_temp_band", sa.String(length=16), nullable=False),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("in_band_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("below_band_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("above_band_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("coverage_pct", sa.Float()),
        sa.Column("median_error_pct", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("run_at", "target_temp_band", "metric", name="uq_cook_behavior_backtests_run_band_metric"),
    )
    op.create_index(
        "ix_cook_behavior_backtests_run_at",
        "cook_behavior_backtests",
        ["run_at"],
    )

    op.create_table(
        "freshdesk_cook_correlations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket_id", sa.String(length=64), nullable=False),
        sa.Column("mac_normalized", sa.String(length=64)),
        sa.Column("ticket_created_at", sa.DateTime(timezone=True)),
        sa.Column("window_start", sa.DateTime(timezone=True)),
        sa.Column("window_end", sa.DateTime(timezone=True)),
        sa.Column("sessions_matched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evidence_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("computed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("ticket_id", name="uq_freshdesk_cook_correlations_ticket"),
    )
    op.create_index(
        "ix_freshdesk_cook_correlations_mac",
        "freshdesk_cook_correlations",
        ["mac_normalized"],
    )


def downgrade() -> None:
    op.drop_index("ix_freshdesk_cook_correlations_mac", table_name="freshdesk_cook_correlations")
    op.drop_table("freshdesk_cook_correlations")
    op.drop_index("ix_cook_behavior_backtests_run_at", table_name="cook_behavior_backtests")
    op.drop_table("cook_behavior_backtests")
    op.drop_index("ix_cook_behavior_baselines_band", table_name="cook_behavior_baselines")
    op.drop_table("cook_behavior_baselines")
