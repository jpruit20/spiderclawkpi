"""page_configs — per-user-per-division layout configuration.

Each row stores the operator's preferred layout for one division
page: which cards are visible, in what order, with optional custom
titles + default time windows. Auth-gated by services/division_ownership
so leads only edit their own division (Joseph edits everything).

config_json shape:
{
  "card_overrides": {
    "shipping_intelligence": {"visible": true, "order": 1, "title": "Shipping Pulse", "default_window_days": 90},
    "sharepoint_activity":   {"visible": false, "order": 99},
    ...
  },
  "default_window_days": 30,
  "accent_color": null,
  "notes": "Optional operator notes"
}

audit_log_json: append-only list of {at, user, change_summary} so
Joseph can review what each lead has changed and revert if needed.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260427_0004"
down_revision = "20260427_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "page_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        # division code (matches division_ownership): cx | marketing | operations | pe | manufacturing
        sa.Column("division", sa.String(32), nullable=False, index=True),
        # Owner email (the lead whose preferences these are). Joseph
        # can also create rows scoped to a division he wants to manage
        # the layout for.
        sa.Column("owner_email", sa.String(255), nullable=False, index=True),
        sa.Column("config_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("audit_log_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_by", sa.String(255)),
        sa.UniqueConstraint("division", "owner_email", name="uq_page_configs_division_owner"),
    )


def downgrade() -> None:
    op.drop_table("page_configs")
