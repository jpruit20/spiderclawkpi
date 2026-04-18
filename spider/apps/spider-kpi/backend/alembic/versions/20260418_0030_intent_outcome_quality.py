"""Add intent + outcome + PID quality columns to telemetry sessions & daily rollup

Revision ID: 20260418_0030
Revises: 20260418_0029
Create Date: 2026-04-18 13:00:00.000000-04:00

Replaces the conflated cook_success / stability_score model with an
intent-vs-outcome split + disturbance-aware PID quality metric. All
new columns are nullable so existing rows stay valid; a re-derivation
script will backfill them from actual_temp_time_series.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "20260418_0030"
down_revision = "20260418_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── telemetry_sessions: per-session intent/outcome/PID quality ──
    op.add_column("telemetry_sessions", sa.Column("cook_intent", sa.String(length=32)))
    op.add_column("telemetry_sessions", sa.Column("cook_outcome", sa.String(length=32)))
    op.add_column("telemetry_sessions", sa.Column("held_target", sa.Boolean(), nullable=True))
    op.add_column("telemetry_sessions", sa.Column("disturbance_count", sa.Integer()))
    op.add_column("telemetry_sessions", sa.Column("total_disturbance_seconds", sa.Integer()))
    op.add_column("telemetry_sessions", sa.Column("avg_recovery_seconds", sa.Integer()))
    op.add_column("telemetry_sessions", sa.Column("in_control_pct", sa.Float()))
    op.add_column("telemetry_sessions", sa.Column("max_overshoot_f", sa.Float()))
    op.add_column("telemetry_sessions", sa.Column("max_undershoot_f", sa.Float()))
    op.add_column("telemetry_sessions", sa.Column("post_reach_samples", sa.Integer()))

    op.create_index("ix_telemetry_sessions_cook_intent", "telemetry_sessions", ["cook_intent"])
    op.create_index("ix_telemetry_sessions_cook_outcome", "telemetry_sessions", ["cook_outcome"])

    # ── telemetry_history_daily: new aggregates ──
    op.add_column("telemetry_history_daily", sa.Column("cook_intents_json", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column("telemetry_history_daily", sa.Column("cook_outcomes_json", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column("telemetry_history_daily", sa.Column("held_target_sessions", sa.Integer()))
    op.add_column("telemetry_history_daily", sa.Column("target_seeking_sessions", sa.Integer()))
    op.add_column("telemetry_history_daily", sa.Column("held_target_rate", sa.Float()))
    op.add_column("telemetry_history_daily", sa.Column("avg_in_control_pct", sa.Float()))
    op.add_column("telemetry_history_daily", sa.Column("avg_disturbances_per_cook", sa.Float()))
    op.add_column("telemetry_history_daily", sa.Column("avg_recovery_seconds", sa.Float()))
    op.add_column("telemetry_history_daily", sa.Column("avg_overshoot_f", sa.Float()))


def downgrade() -> None:
    op.drop_column("telemetry_history_daily", "avg_overshoot_f")
    op.drop_column("telemetry_history_daily", "avg_recovery_seconds")
    op.drop_column("telemetry_history_daily", "avg_disturbances_per_cook")
    op.drop_column("telemetry_history_daily", "avg_in_control_pct")
    op.drop_column("telemetry_history_daily", "held_target_rate")
    op.drop_column("telemetry_history_daily", "target_seeking_sessions")
    op.drop_column("telemetry_history_daily", "held_target_sessions")
    op.drop_column("telemetry_history_daily", "cook_outcomes_json")
    op.drop_column("telemetry_history_daily", "cook_intents_json")

    op.drop_index("ix_telemetry_sessions_cook_outcome", table_name="telemetry_sessions")
    op.drop_index("ix_telemetry_sessions_cook_intent", table_name="telemetry_sessions")
    op.drop_column("telemetry_sessions", "post_reach_samples")
    op.drop_column("telemetry_sessions", "max_undershoot_f")
    op.drop_column("telemetry_sessions", "max_overshoot_f")
    op.drop_column("telemetry_sessions", "in_control_pct")
    op.drop_column("telemetry_sessions", "avg_recovery_seconds")
    op.drop_column("telemetry_sessions", "total_disturbance_seconds")
    op.drop_column("telemetry_sessions", "disturbance_count")
    op.drop_column("telemetry_sessions", "held_target")
    op.drop_column("telemetry_sessions", "cook_outcome")
    op.drop_column("telemetry_sessions", "cook_intent")
