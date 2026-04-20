"""Firmware Phase 2 — binary metadata, per-cohort approval, deploy audit log.

Revision ID: 20260421_0001
Revises: 20260420_0036
Create Date: 2026-04-21

Phase 2 of the Firmware Hub (Joseph 2026-04-21). This migration adds the
schema the dashboard needs to orchestrate OTA pushes through AWS IoT Jobs
without bricking field devices.

Changes:

* Extend ``firmware_releases`` with binary metadata (url, sha256, size,
  target_controller_model) and per-cohort approval flags
  (approved_for_alpha / beta / gamma + append-only approval_audit_json
  trail). Approval is per-cohort because Alpha can ship long before Beta
  approval, and Beta can ship long before Gamma.
* ``firmware_deploy_log`` — one row per (device, deploy attempt). This
  is the audit trail for the circuit breaker and for post-mortems. No
  deletes; status transitions are immutable history.
* ``firmware_deploy_preview_tokens`` — single-use tokens that bridge the
  two-phase /preview → /execute flow. A /execute call must present a
  token issued by a recent /preview with matching release + device set.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "20260421_0001"
down_revision = "20260420_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("firmware_releases", sa.Column("binary_url", sa.String(1024), nullable=True))
    op.add_column("firmware_releases", sa.Column("binary_sha256", sa.String(64), nullable=True))
    op.add_column("firmware_releases", sa.Column("binary_size_bytes", sa.Integer(), nullable=True))
    op.add_column("firmware_releases", sa.Column("target_controller_model", sa.String(32), nullable=True))
    op.add_column(
        "firmware_releases",
        sa.Column("approved_for_alpha", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "firmware_releases",
        sa.Column("approved_for_beta", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "firmware_releases",
        sa.Column("approved_for_gamma", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "firmware_releases",
        sa.Column("approval_audit_json", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )

    op.create_table(
        "firmware_deploy_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "release_id",
            sa.Integer(),
            sa.ForeignKey("firmware_releases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("device_id", sa.String(128), nullable=False),
        sa.Column("mac", sa.String(12), nullable=True),
        sa.Column("cohort", sa.String(16), nullable=False),
        sa.Column("initiated_by", sa.String(128), nullable=False),
        sa.Column("aws_job_id", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("target_version", sa.String(64), nullable=False),
        sa.Column("prior_version", sa.String(64), nullable=True),
        sa.Column("preflight_results_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("override_reasons_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("aws_response_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_firmware_deploy_log_release", "firmware_deploy_log", ["release_id"])
    op.create_index("ix_firmware_deploy_log_device", "firmware_deploy_log", ["device_id"])
    op.create_index("ix_firmware_deploy_log_aws_job_id", "firmware_deploy_log", ["aws_job_id"])
    op.create_index(
        "ix_firmware_deploy_log_status_created",
        "firmware_deploy_log",
        ["status", "created_at"],
    )

    op.create_table(
        "firmware_deploy_preview_tokens",
        sa.Column("token", sa.String(64), primary_key=True),
        sa.Column(
            "release_id",
            sa.Integer(),
            sa.ForeignKey("firmware_releases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cohort", sa.String(16), nullable=False),
        sa.Column("device_ids_json", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("preflight_results_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_firmware_deploy_preview_tokens_expires_at",
        "firmware_deploy_preview_tokens",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_firmware_deploy_preview_tokens_expires_at", table_name="firmware_deploy_preview_tokens")
    op.drop_table("firmware_deploy_preview_tokens")

    op.drop_index("ix_firmware_deploy_log_status_created", table_name="firmware_deploy_log")
    op.drop_index("ix_firmware_deploy_log_aws_job_id", table_name="firmware_deploy_log")
    op.drop_index("ix_firmware_deploy_log_device", table_name="firmware_deploy_log")
    op.drop_index("ix_firmware_deploy_log_release", table_name="firmware_deploy_log")
    op.drop_table("firmware_deploy_log")

    op.drop_column("firmware_releases", "approval_audit_json")
    op.drop_column("firmware_releases", "approved_for_gamma")
    op.drop_column("firmware_releases", "approved_for_beta")
    op.drop_column("firmware_releases", "approved_for_alpha")
    op.drop_column("firmware_releases", "target_controller_model")
    op.drop_column("firmware_releases", "binary_size_bytes")
    op.drop_column("firmware_releases", "binary_sha256")
    op.drop_column("firmware_releases", "binary_url")
