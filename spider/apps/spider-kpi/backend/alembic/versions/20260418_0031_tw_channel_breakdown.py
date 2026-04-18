"""Add per-channel ad-spend columns to tw_summary_daily / tw_summary_intraday

Revision ID: 20260418_0031
Revises: 20260418_0030
Create Date: 2026-04-18 15:00:00.000000-04:00

Context (Joseph, 2026-04-18): we may not renew Triple Whale next
month. Before renewal comes due, we want to (a) be pulling all
channel-level spend data not just blended, (b) have a portable
archive of everything TW has for us. Step one is to widen the
summary tables so the connector's existing per-channel fallback
becomes a first-class stored field rather than a one-shot fallback.

All columns default to 0.0 so existing rows stay valid; a backfill
script (``scripts/tw_backfill_channel_spends.py``) re-derives them
from the raw payloads we've already stored in ``tw_raw_payloads``,
so no new TW API calls are required to populate historical days.

``channel_metrics_json`` is a flexible catch-all for future
per-channel metrics (revenue, ROAS, orders, impressions, clicks)
so we don't need another migration to capture those — they'll be
derived from the raw payload and written here.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "20260418_0031"
down_revision = "20260418_0030"
branch_labels = None
depends_on = None


SPEND_COLUMNS = [
    "facebook_spend",
    "google_spend",
    "tiktok_spend",
    "snapchat_spend",
    "pinterest_spend",
    "bing_spend",
    "twitter_spend",
    "reddit_spend",
    "linkedin_spend",
    "amazon_ads_spend",
    "smsbump_spend",
    "omnisend_spend",
    "postscript_spend",
    "taboola_spend",
    "outbrain_spend",
    "stackadapt_spend",
    "adroll_spend",
    "impact_spend",
    "custom_spend",
]


def upgrade() -> None:
    for table in ("tw_summary_daily", "tw_summary_intraday"):
        for col in SPEND_COLUMNS:
            op.add_column(
                table,
                sa.Column(col, sa.Float(), server_default="0", nullable=False),
            )
        op.add_column(
            table,
            sa.Column(
                "channel_metrics_json",
                JSONB(),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
        )


def downgrade() -> None:
    for table in ("tw_summary_daily", "tw_summary_intraday"):
        op.drop_column(table, "channel_metrics_json")
        for col in reversed(SPEND_COLUMNS):
            op.drop_column(table, col)
