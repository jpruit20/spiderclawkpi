"""Lore events — institutional-memory timeline of business events.

Revision ID: 20260419_0034
Revises: 20260419_0033
Create Date: 2026-04-19 19:45:00.000000-04:00

Phase 1 piece 2 of the company-lore surface (Joseph 2026-04-19).
Captures the "what was happening at Spider Grills on this date" context
that explains chart anomalies — product launches, firmware rollouts,
hardware revisions, marketing campaigns, outages, holidays, personnel
changes, press mentions, external market events.

The primary read pattern is "give me all events that overlap the date
range [start, end]" so the frontend can overlay timeline pins on any
chart. Secondary read pattern is "all events for a division" so each
division page can list its own history.

Events have soft start/end — end_date is nullable for single-day or
still-open events. source_type tracks whether Joseph created the event
manually or whether it was auto-extracted from email/slack/clickup/deci
by an Opus seeding pass. confidence distinguishes "Joseph confirmed
this" from "Opus guessed from an email thread".

Unique constraint on (title, start_date) to make seeding idempotent —
re-running the Opus archive pass won't create duplicates.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "20260419_0034"
down_revision = "20260419_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lore_events",
        sa.Column("id", sa.Integer(), primary_key=True),

        # Canonical event_type. Not an enum so new types don't need migrations.
        # Known types: launch, incident, campaign, promotion, firmware,
        # hardware_revision, personnel, press, external, holiday, other.
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),

        # Time span. end_date NULL = single-day or still-active.
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),

        # Division scoping — which dashboard page does this event belong to?
        # NULL = company-wide (shows on every division overlay).
        # Values: commercial, support, marketing, product_engineering,
        # executive, deci, or NULL.
        sa.Column("division", sa.String(length=32), nullable=True),

        # confirmed — Joseph said it happened; inferred — pulled from
        # email/slack with high signal; rumored — Opus extracted but
        # human hasn't confirmed.
        sa.Column("confidence", sa.String(length=16), nullable=False, server_default="confirmed"),

        # manual, email_archive, slack, clickup, deci, ai_opus, etc.
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("source_refs_json", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),

        # {color: '#ff6d7a', tags: ['memorial-day', 'sitewide'], magnitude: 'high'}
        sa.Column("metadata_json", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),

        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),

        sa.UniqueConstraint("title", "start_date", name="uq_lore_events_title_start"),
    )
    op.create_index("ix_lore_events_start_date", "lore_events", ["start_date"])
    op.create_index("ix_lore_events_end_date", "lore_events", ["end_date"])
    op.create_index("ix_lore_events_division", "lore_events", ["division"])
    op.create_index("ix_lore_events_event_type", "lore_events", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_lore_events_event_type", table_name="lore_events")
    op.drop_index("ix_lore_events_division", table_name="lore_events")
    op.drop_index("ix_lore_events_end_date", table_name="lore_events")
    op.drop_index("ix_lore_events_start_date", table_name="lore_events")
    op.drop_table("lore_events")
