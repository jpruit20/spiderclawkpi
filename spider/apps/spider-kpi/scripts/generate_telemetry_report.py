#!/usr/bin/env python3
"""Generate a telemetry analysis report (comprehensive or monthly).

CLI entrypoint used by:
  * Manual runs: `.venv/bin/python scripts/generate_telemetry_report.py --type comprehensive`
  * Monthly systemd timer: `.venv/bin/python scripts/generate_telemetry_report.py --type monthly`

After writing the row to telemetry_reports, also dumps the markdown body
to docs/telemetry_analysis_<YYYYMMDD>_<type>.md so the report is easy
to browse in the repo and share.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


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

from app.compute.telemetry_analysis import generate_report  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import TelemetryReport  # noqa: E402
from sqlalchemy import select  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--type", choices=["comprehensive", "monthly"], default="monthly")
    p.add_argument("--force", action="store_true", help="Regenerate even if today already has a report of this type.")
    p.add_argument("--docs-dir", type=Path, default=Path(__file__).resolve().parents[3] / "docs", help="Where to write the markdown dump.")
    args = p.parse_args()

    db = SessionLocal()
    try:
        result = generate_report(db, report_type=args.type, save=True, force=args.force)
        print(json.dumps({k: v for k, v in result.items() if k != "body_markdown"}, default=str, indent=2))
        if not result.get("ok"):
            return 1
        rid = result.get("id")
        if rid:
            report = db.get(TelemetryReport, rid)
            if report:
                args.docs_dir.mkdir(parents=True, exist_ok=True)
                today = datetime.now(ZoneInfo("America/New_York")).date()
                fname = args.docs_dir / f"telemetry_analysis_{today.isoformat()}_{args.type}.md"
                fname.write_text(report.body_markdown, encoding="utf-8")
                print(f"Markdown written to: {fname}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
