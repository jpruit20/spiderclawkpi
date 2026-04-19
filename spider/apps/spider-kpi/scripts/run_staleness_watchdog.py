#!/usr/bin/env python3
"""Staleness watchdog entrypoint.

Runs the watchdog checks, prints the report, and if anything is stale,
sends a Slack DM (with SES email fallback) to Joseph.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
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

from app.compute.staleness_watchdog import format_slack_message, run  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.email_allowlist import assert_allowed  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.push_alerts import send_slack_dm_to_email  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="Print report, do not DM.")
    p.add_argument("--always-dm", action="store_true", help="DM even if nothing is stale (useful for first-run sanity).")
    args = p.parse_args()

    settings = get_settings()
    recipient = assert_allowed(settings.push_alerts_recipient_email)[0]

    db = SessionLocal()
    try:
        report = run(db)
        print(json.dumps(report, default=str, indent=2))

        stale_count = report.get("stale_count", 0)
        if stale_count == 0 and not args.always_dm:
            return 0
        if args.dry_run:
            print(f"--dry-run: would have DM'd {recipient} ({stale_count} stale)")
            return 0

        text = format_slack_message(report) or ":white_check_mark: Spider KPI — all watched tables are fresh."
        # Use a bucketed subject_id: one alert per day per unique stale set
        stale_key = ",".join(sorted(s["table"] for s in report.get("stale", [])))
        now = datetime.now(timezone.utc)
        subject_id = f"staleness:{now.strftime('%Y%m%d')}:{stale_key or 'ok'}"

        sent = send_slack_dm_to_email(
            db,
            recipient_email=recipient,
            subject_type="staleness_alert",
            subject_id=subject_id,
            text=text,
            bypass_quiet_hours=True,
            bypass_rate_limit=True,
        )
        print(f"slack_dm_sent={sent} stale_count={stale_count}")
        return 0 if sent or stale_count == 0 else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
