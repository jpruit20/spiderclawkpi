#!/usr/bin/env python3
"""Generate cross-source AI insights for today.

Runs once per morning (systemd timer at 6am ET, before the 7am digest email)
so the morning brief + digest ship with fresh observations from Opus.

Fail-silent on missing ANTHROPIC_API_KEY or API errors — the dashboard's
other data is never blocked on insight generation.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)", line)
        if not m:
            continue
        key, value = m.group(1), m.group(2)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_dotenv(ENV_PATH)

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.compute.daily_insights import generate_insights  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        result = generate_insights(db, save=True)
    finally:
        db.close()
    print(json.dumps(result, default=str, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
