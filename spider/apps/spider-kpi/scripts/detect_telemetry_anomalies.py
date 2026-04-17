#!/usr/bin/env python3
"""Score yesterday's telemetry vs the trailing-14d baseline and persist
any anomalies found. Runs nightly via systemd timer."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
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

from app.compute.telemetry_anomalies import backfill_anomalies, detect_anomalies  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--date", type=_parse_date, default=None, help="Score a specific date. Default: yesterday (latest complete day).")
    p.add_argument("--backfill-from", type=_parse_date, default=None, help="Score every day from this date through yesterday.")
    p.add_argument("--backfill-to", type=_parse_date, default=None)
    args = p.parse_args()

    db = SessionLocal()
    try:
        if args.backfill_from:
            result = backfill_anomalies(db, start_date=args.backfill_from, end_date=args.backfill_to)
        else:
            result = detect_anomalies(db, business_date=args.date, persist=True)
        print(json.dumps(result, default=str, indent=2))
        return 0 if result.get("ok") else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
