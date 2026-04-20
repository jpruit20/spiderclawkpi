"""Firmware beta + gamma program — editable issue taxonomy, release
profiles, beta cohort membership.

Revision ID: 20260420_0035
Revises: 20260419_0034
Create Date: 2026-04-20

Phase 1 of the Firmware Beta + Gamma Waves program (Joseph 2026-04-20).

* ``firmware_issue_tags`` — editable taxonomy of failure modes a
  firmware release can address. Kept as a table (not an enum) so Joseph
  can add / edit tags on the dashboard as new failure modes emerge.
  Seeded with an initial set; slugs are stable so release-profile rows
  reference tags by slug.
* ``firmware_releases`` — per-release profile. Each release names the
  issue-tag slugs it addresses, tracks its AWS IoT Jobs ids, approval
  state, and Gamma-wave schedule.
* ``beta_cohort_members`` — per-device opt-in state for each beta
  release. Tracks which release, when they opted in, and — once the
  release is evaluated — whether their device's targeted signatures
  cleared after the firmware pushed.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "20260420_0035"
down_revision = "20260419_0034"
branch_labels = None
depends_on = None


INITIAL_TAGS = [
    # (slug, label, description)
    ("probe_dropout",       "Probe dropout",             "Probe readings briefly drop to 0 / invalid mid-cook."),
    ("persistent_overshoot","Persistent overshoot",      "Actual temp sustains >15°F above target post-reach."),
    ("persistent_undershoot","Persistent undershoot",    "Actual temp sustains >15°F below target post-reach."),
    ("slow_recovery",       "Slow recovery after lid-open", "PID takes >5 min to return to target after a disturbance."),
    ("startup_fail",        "Startup fail",              "Device never reaches target; user aborts or switches to manual."),
    ("wifi_disconnect",     "Wi-Fi disconnect mid-cook", "Device drops connectivity for >60s during an active cook."),
    ("oscillation",         "Oscillation around target", "PID oscillates >±20°F without settling."),
    ("error_code_42",       "Error code 42",             "Firmware reports error code 42 during a cook."),
    ("app_sync_lag",        "App sync lag",              "Mobile app state lags device shadow by >30s."),
]


def upgrade() -> None:
    op.create_table(
        "firmware_issue_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # Soft-delete so existing release rows still resolve their tags.
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.UniqueConstraint("slug", name="uq_firmware_issue_tags_slug"),
    )

    op.create_table(
        "firmware_releases",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Human-friendly label (e.g. "01.01.98"); unique so re-imports
        # from ClickUp stay idempotent.
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),

        # Array of firmware_issue_tags.slug. Kept as an array rather
        # than a join table because the ordering matters for the Opus
        # post-deploy verification report.
        sa.Column("addresses_issues", sa.ARRAY(sa.String(length=64)), nullable=False, server_default=sa.text("ARRAY[]::varchar[]")),

        # draft -> beta -> beta_evaluating -> approved -> gamma -> ga -> rolled_back
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),

        # ClickUp / git cross-refs (populate later).
        sa.Column("clickup_task_id", sa.String(length=64), nullable=True),
        sa.Column("git_commit_sha", sa.String(length=64), nullable=True),

        # AWS IoT Jobs — beta push and gamma waves.
        sa.Column("beta_iot_job_id", sa.String(length=128), nullable=True),
        sa.Column("gamma_iot_job_ids_json", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),

        # Gamma rollout plan (populated on approval). Shape:
        # { "waves": [{"day": 1, "target_pct": 10, "started_at": null,
        #              "iot_job_id": null, "halted": false}, ...],
        #   "cohort_order": "tenure_desc_then_usage_desc" }
        sa.Column("gamma_plan_json", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),

        # Evaluation artefacts.
        sa.Column("beta_report_json", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("beta_cohort_target_size", sa.Integer(), nullable=False, server_default="100"),

        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("approved_by", sa.String(length=128), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),

        sa.UniqueConstraint("version", name="uq_firmware_releases_version"),
    )
    op.create_index("ix_firmware_releases_status", "firmware_releases", ["status"])

    op.create_table(
        "beta_cohort_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("release_id", sa.Integer(), sa.ForeignKey("firmware_releases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=True),

        # Score used to rank the device at selection time (0-1).
        sa.Column("candidate_score", sa.Float(), nullable=True),
        # Snapshot of why this device was a candidate. Shape:
        # { "matched_tags": ["probe_dropout"], "matched_freshdesk_tickets": [...],
        #   "sessions_30d": 12, "tenure_days": 380, "signals": [...] }
        sa.Column("candidate_reason_json", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),

        # invited -> opted_in -> ota_pushed -> ota_confirmed -> evaluated -> declined / expired
        sa.Column("state", sa.String(length=32), nullable=False, server_default="invited"),

        sa.Column("invited_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("opted_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opt_in_source", sa.String(length=32), nullable=True),  # web, email, app
        sa.Column("ota_pushed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ota_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),

        # Per-device post-deploy verdict vs its own pre-release baseline.
        sa.Column("verdict_json", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),

        sa.UniqueConstraint("release_id", "device_id", name="uq_beta_cohort_release_device"),
    )
    op.create_index("ix_beta_cohort_state", "beta_cohort_members", ["state"])
    op.create_index("ix_beta_cohort_device_id", "beta_cohort_members", ["device_id"])

    # Seed the initial taxonomy so the dashboard has something to render.
    op.bulk_insert(
        sa.table(
            "firmware_issue_tags",
            sa.column("slug", sa.String),
            sa.column("label", sa.String),
            sa.column("description", sa.Text),
            sa.column("archived", sa.Boolean),
            sa.column("created_by", sa.String),
        ),
        [
            {"slug": slug, "label": label, "description": desc, "archived": False, "created_by": "seed"}
            for (slug, label, desc) in INITIAL_TAGS
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_beta_cohort_device_id", table_name="beta_cohort_members")
    op.drop_index("ix_beta_cohort_state", table_name="beta_cohort_members")
    op.drop_table("beta_cohort_members")
    op.drop_index("ix_firmware_releases_status", table_name="firmware_releases")
    op.drop_table("firmware_releases")
    op.drop_table("firmware_issue_tags")
