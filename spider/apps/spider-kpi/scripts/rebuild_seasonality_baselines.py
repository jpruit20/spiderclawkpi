#!/usr/bin/env python3
"""Rebuild seasonality baselines — runs nightly after the daily materializers.

Computes per-metric, per-day-of-year distributions (p10/p25/p50/p75/p90
plus mean + stddev) from kpi_daily / telemetry_history_daily /
freshdesk_tickets_daily. Output lands in ``seasonality_baselines`` and
powers "running hot/cold" interpretation across the dashboard.

Idempotent — upserts in place. Current-year observations are excluded
from the baseline (we don't want today comparing itself to itself).

Usage:
    python scripts/rebuild_seasonality_baselines.py
    python scripts/rebuild_seasonality_baselines.py --metric revenue
    python scripts/rebuild_seasonality_baselines.py --include-current-year  # for testing
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
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

from app.db.session import SessionLocal  # noqa: E402
from app.services.seasonality import (  # noqa: E402
    METRICS,
    rebuild_all_baselines,
    rebuild_baselines_for_metric,
    _metric_by_name,
)


logger = logging.getLogger("seasonality_rebuild")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--metric", type=str, default=None, help="rebuild just one metric")
    p.add_argument("--include-current-year", action="store_true",
                   help="include current-year samples (testing only — normally excluded)")
    args = p.parse_args()

    with SessionLocal() as db:
        if args.metric:
            spec = _metric_by_name(args.metric)
            if spec is None:
                available = ", ".join(m.name for m in METRICS)
                logger.error("unknown metric %r. Available: %s", args.metric, available)
                return 2
            n = rebuild_baselines_for_metric(
                db, spec, exclude_current_year=not args.include_current_year
            )
            db.commit()
            logger.info("done: rebuilt %d DoY rows for %s", n, args.metric)
        else:
            stats = rebuild_all_baselines(db)
            total = sum(v for v in stats.values() if v > 0)
            errors = sum(1 for v in stats.values() if v < 0)
            logger.info("done: %d baseline rows across %d metrics (%d errors)",
                        total, len(stats), errors)
            return 0 if errors == 0 else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
