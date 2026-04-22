"""Charcoal JIT invitations — the private-beta invite engine.

Revision ID: 20260425_0007
Revises: 20260425_0006
Create Date: 2026-04-22

One row per invitation. Invitations go to the top-N devices in the
addressable cohort (percentile-selected) and expire after a configurable
window (14 days by default). The token column is the shareable secret
the app-side uses to verify the invite on an opt-in landing screen.

Accepted invitations promote the row to ``status='accepted'`` and stamp
``subscription_id`` so we can trace every subscription back to the
batch + percentile + burn-rate snapshot that justified inviting it.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260425_0007"
down_revision = "20260425_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "charcoal_jit_invitations",
        sa.Column("id", sa.Integer(), primary_key=True),
        # batch_id groups invitations sent together so we can audit
        # "batch X: 50 invites, 18 accepted, 3 declined" at a glance.
        sa.Column("batch_id", postgresql.UUID(as_uuid=False), nullable=False, index=True),
        # invitation_token is the URL secret. App-side hits
        # /api/charcoal/jit/invitations/{token} to resolve a pending invite
        # before showing the opt-in screen.
        sa.Column(
            "invitation_token",
            postgresql.UUID(as_uuid=False),
            nullable=False,
            unique=True,
        ),
        # Which device we selected. device_id can drift over firmware
        # re-provisions, so we also capture mac_normalized as the stable
        # handle. At least one of the two must be non-null.
        sa.Column("device_id", sa.String(128), nullable=True),
        sa.Column("mac_normalized", sa.String(12), nullable=True),
        # user_key is the customer the app resolves at acceptance time
        # (email usually). We don't require it at invite creation because
        # we're selecting on the device, not on a user record — the
        # person who logs in on that grill claims the invite.
        sa.Column("user_key", sa.String(128), nullable=True),
        # Pinned SKU + params snapshotted at invite time.
        sa.Column(
            "partner_product_id",
            sa.Integer(),
            sa.ForeignKey("partner_products.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("bag_size_lb", sa.Integer(), nullable=False),
        sa.Column("fuel_preference", sa.String(16), nullable=False),
        sa.Column("margin_pct", sa.Float(), nullable=False, server_default="10.0"),
        # Analytics snapshot — what the modeler said about this device
        # at the moment of invite. Lets us compare cohort projections
        # to actual performance as the beta matures.
        sa.Column("addressable_lb_per_month", sa.Float(), nullable=True),
        sa.Column("percentile_at_invite", sa.Float(), nullable=True),
        sa.Column("sessions_in_window_at_invite", sa.Integer(), nullable=True),
        sa.Column("product_family_at_invite", sa.String(64), nullable=True),
        # Full cohort-selection config (lookback, percentile floor,
        # families, min_cooks) snapshotted for audit — lets us answer
        # "why was THIS device in THAT batch" months from now.
        sa.Column(
            "cohort_params_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # Lifecycle.
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "invited_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invited_by", sa.String(128), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        # FK back to the subscription once accepted. SET NULL so a
        # subscription cascade-delete doesn't also wipe the invite row.
        sa.Column(
            "subscription_id",
            sa.Integer(),
            sa.ForeignKey("charcoal_jit_subscriptions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_charcoal_jit_invitations_device_id",
        "charcoal_jit_invitations",
        ["device_id"],
    )
    op.create_index(
        "ix_charcoal_jit_invitations_mac",
        "charcoal_jit_invitations",
        ["mac_normalized"],
    )
    op.create_index(
        "ix_charcoal_jit_invitations_status",
        "charcoal_jit_invitations",
        ["status"],
    )
    op.create_index(
        "ix_charcoal_jit_invitations_expires_at",
        "charcoal_jit_invitations",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_charcoal_jit_invitations_expires_at",
        table_name="charcoal_jit_invitations",
    )
    op.drop_index(
        "ix_charcoal_jit_invitations_status",
        table_name="charcoal_jit_invitations",
    )
    op.drop_index(
        "ix_charcoal_jit_invitations_mac",
        table_name="charcoal_jit_invitations",
    )
    op.drop_index(
        "ix_charcoal_jit_invitations_device_id",
        table_name="charcoal_jit_invitations",
    )
    op.drop_table("charcoal_jit_invitations")
