#!/usr/bin/env python3
"""Backfill per-channel spend columns on tw_summary_daily /
tw_summary_intraday from already-stored TWRawPayload rows.

Why this exists: the 2026-04-18 migration added 19 per-channel spend
columns. The connector writes them on every new sync, but existing
historical rows have 0.0 everywhere until we re-parse the raw
responses we've already stored. This script does that — zero TW API
calls needed, since ``tw_raw_payloads`` already has the full JSON
responses going back to whenever the connector first ran.

Safe to re-run: idempotent, updates by business_date.

Usage:
    python scripts/tw_backfill_channel_spends.py                # all raw rows
    python scripts/tw_backfill_channel_spends.py --limit 30     # spot-check run
    python scripts/tw_backfill_channel_spends.py --since 2024-01-01
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path


ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def _load_env(p: Path) -> None:
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
            v = v[1:-1]
        os.environ.setdefault(k.strip(), v)


_load_env(ENV_PATH)

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.ingestion.connectors.triplewhale import (  # noqa: E402
    _apply_summary_fields,
    _normalize,
)
from app.models import TWRawPayload, TWSummaryDaily, TWSummaryIntraday  # noqa: E402


logger = logging.getLogger("tw_backfill_channels")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def _parse_since(s: str | None) -> date | None:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()


def run(limit: int | None, since: date | None) -> int:
    updated = 0
    skipped = 0
    errors = 0
    with SessionLocal() as db:
        stmt = select(TWRawPayload).order_by(TWRawPayload.business_date)
        if since is not None:
            stmt = stmt.where(TWRawPayload.business_date >= since)
        if limit is not None:
            stmt = stmt.limit(limit)

        rows = db.execute(stmt).scalars().all()
        logger.info("found %d raw payload rows to re-derive", len(rows))

        for i, raw in enumerate(rows, start=1):
            if not raw.business_date:
                skipped += 1
                continue
            try:
                normalized = _normalize(
                    raw.response_payload,
                    raw.request_payload or {
                        "period": {
                            "start": raw.business_date.isoformat(),
                            "end": raw.business_date.isoformat(),
                        }
                    },
                )

                daily = db.execute(
                    select(TWSummaryDaily).where(
                        TWSummaryDaily.business_date == raw.business_date
                    )
                ).scalars().first()
                if daily is None:
                    daily = TWSummaryDaily(business_date=raw.business_date)
                    db.add(daily)
                _apply_summary_fields(daily, normalized)

                # Re-derive matching intraday bucket (historical days
                # use UTC-midnight buckets per the connector convention;
                # today's row gets whatever current_hour_bucket was at
                # last sync — we don't touch it here).
                bucket = datetime.combine(
                    raw.business_date,
                    datetime.min.time(),
                    tzinfo=timezone.utc,
                )
                intra = db.execute(
                    select(TWSummaryIntraday).where(
                        TWSummaryIntraday.bucket_start == bucket
                    )
                ).scalars().first()
                if intra is not None:
                    _apply_summary_fields(intra, normalized)

                updated += 1
                if i % 50 == 0:
                    db.commit()
                    logger.info("  committed through row %d (%s)", i, raw.business_date)
            except Exception:
                errors += 1
                logger.exception("failed on business_date=%s", raw.business_date)

        db.commit()

    logger.info(
        "done: updated=%d skipped=%d errors=%d", updated, skipped, errors
    )
    return 0 if errors == 0 else 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="max rows to re-derive")
    ap.add_argument("--since", type=str, default=None, help="only re-derive dates >= YYYY-MM-DD")
    args = ap.parse_args()
    return run(limit=args.limit, since=_parse_since(args.since))


if __name__ == "__main__":
    raise SystemExit(main())
