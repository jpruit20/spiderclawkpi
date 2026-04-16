"""Add app-side observation tables (Freshdesk + app backend) for telemetry

Creates three tables that hold app-side fleet data distinct from the existing
device-telemetry pipeline:

  * ``app_side_user_observations`` — raw per-source user sightings
  * ``app_side_device_observations`` — raw per-source user-device-pairing sightings
  * ``app_side_daily`` — per-day rollup, split by ``source`` column

Every row carries a ``source`` discriminator (``'freshdesk'`` or ``'app_backend'``)
so the two streams can be reported separately or merged (deduped by MAC /
user_key) without double-counting. Initial build only writes ``'freshdesk'``
rows; the ``'app_backend'`` source is wired in once direct DB credentials for
``spidergrills.app`` are available.

Revision ID: 20260416_0022
Revises: 20260415_0021
Create Date: 2026-04-16 00:00:00.000000+00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "20260416_0022"
down_revision = "20260415_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_side_user_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_date", sa.Date(), nullable=False, index=True),
        sa.Column("source", sa.String(length=32), nullable=False, index=True),
        sa.Column("source_ref_id", sa.String(length=128), nullable=False),
        sa.Column("user_key", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=255)),
        sa.Column("email_domain", sa.String(length=255)),
        sa.Column("observed_at", sa.DateTime(timezone=True)),
        sa.Column("raw_payload", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source", "source_ref_id", name="uq_app_side_user_observations_source_ref"),
    )
    op.create_index(
        "ix_app_side_user_observations_business_date_source",
        "app_side_user_observations",
        ["business_date", "source"],
    )
    op.create_index(
        "ix_app_side_user_observations_user_key",
        "app_side_user_observations",
        ["user_key"],
    )
    op.create_index(
        "ix_app_side_user_observations_email",
        "app_side_user_observations",
        ["email"],
    )
    op.create_index(
        "ix_app_side_user_observations_observed_at",
        "app_side_user_observations",
        ["observed_at"],
    )

    op.create_table(
        "app_side_device_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_date", sa.Date(), nullable=False, index=True),
        sa.Column("source", sa.String(length=32), nullable=False, index=True),
        sa.Column("source_ref_id", sa.String(length=128), nullable=False),
        sa.Column("user_key", sa.String(length=128)),
        sa.Column("mac_raw", sa.String(length=64)),
        sa.Column("mac_normalized", sa.String(length=64)),
        sa.Column("controller_model", sa.String(length=64)),
        sa.Column("firmware_version", sa.String(length=64)),
        sa.Column("app_version", sa.String(length=64)),
        sa.Column("phone_os", sa.String(length=32)),
        sa.Column("phone_os_version", sa.String(length=32)),
        sa.Column("phone_brand", sa.String(length=64)),
        sa.Column("phone_model", sa.String(length=128)),
        sa.Column("observed_at", sa.DateTime(timezone=True)),
        sa.Column("raw_payload", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source", "source_ref_id", name="uq_app_side_device_observations_source_ref"),
    )
    op.create_index(
        "ix_app_side_device_observations_business_date_source",
        "app_side_device_observations",
        ["business_date", "source"],
    )
    op.create_index(
        "ix_app_side_device_observations_mac",
        "app_side_device_observations",
        ["mac_normalized"],
    )
    op.create_index(
        "ix_app_side_device_observations_user_key",
        "app_side_device_observations",
        ["user_key"],
    )
    op.create_index(
        "ix_app_side_device_observations_controller_model",
        "app_side_device_observations",
        ["controller_model"],
    )
    op.create_index(
        "ix_app_side_device_observations_firmware_version",
        "app_side_device_observations",
        ["firmware_version"],
    )
    op.create_index(
        "ix_app_side_device_observations_app_version",
        "app_side_device_observations",
        ["app_version"],
    )
    op.create_index(
        "ix_app_side_device_observations_phone_os",
        "app_side_device_observations",
        ["phone_os"],
    )
    op.create_index(
        "ix_app_side_device_observations_phone_brand",
        "app_side_device_observations",
        ["phone_brand"],
    )
    op.create_index(
        "ix_app_side_device_observations_observed_at",
        "app_side_device_observations",
        ["observed_at"],
    )

    op.create_table(
        "app_side_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("observations", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unique_users", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unique_devices", sa.Integer(), server_default="0", nullable=False),
        sa.Column("app_version_dist", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("firmware_version_dist", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("controller_model_dist", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("phone_os_dist", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("phone_brand_dist", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("phone_model_dist", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("business_date", "source", name="uq_app_side_daily_date_source"),
    )
    op.create_index(
        "ix_app_side_daily_business_date",
        "app_side_daily",
        ["business_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_app_side_daily_business_date", table_name="app_side_daily")
    op.drop_table("app_side_daily")

    op.drop_index("ix_app_side_device_observations_observed_at", table_name="app_side_device_observations")
    op.drop_index("ix_app_side_device_observations_phone_brand", table_name="app_side_device_observations")
    op.drop_index("ix_app_side_device_observations_phone_os", table_name="app_side_device_observations")
    op.drop_index("ix_app_side_device_observations_app_version", table_name="app_side_device_observations")
    op.drop_index("ix_app_side_device_observations_firmware_version", table_name="app_side_device_observations")
    op.drop_index("ix_app_side_device_observations_controller_model", table_name="app_side_device_observations")
    op.drop_index("ix_app_side_device_observations_user_key", table_name="app_side_device_observations")
    op.drop_index("ix_app_side_device_observations_mac", table_name="app_side_device_observations")
    op.drop_index("ix_app_side_device_observations_business_date_source", table_name="app_side_device_observations")
    op.drop_table("app_side_device_observations")

    op.drop_index("ix_app_side_user_observations_observed_at", table_name="app_side_user_observations")
    op.drop_index("ix_app_side_user_observations_email", table_name="app_side_user_observations")
    op.drop_index("ix_app_side_user_observations_user_key", table_name="app_side_user_observations")
    op.drop_index("ix_app_side_user_observations_business_date_source", table_name="app_side_user_observations")
    op.drop_table("app_side_user_observations")
