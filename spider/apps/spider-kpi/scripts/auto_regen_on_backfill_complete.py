#!/usr/bin/env python3
"""Watch for v2 S3 backfill completion; regenerate the comprehensive
telemetry report and score historical anomalies once it finishes.

Runs every 15 minutes via systemd timer overnight. Uses a flag file
(/var/lib/spider-kpi/comprehensive-regen-done) to make the work
idempotent — once the regeneration has fired, subsequent invocations
are no-ops.

Completion criteria (all must be true):
  1. No ``import_s3_history_v2`` Python process running.
  2. Backfill temp dir is gone OR empty.
  3. ``telemetry_sessions`` has at least MIN_SESSIONS rows
     (current baseline is 7; after a successful backfill this jumps
     into the tens of thousands).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
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

from sqlalchemy import func, select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models import TelemetrySession  # noqa: E402

FLAG_DIR = Path("/var/lib/spider-kpi")
FLAG_FILE = FLAG_DIR / "comprehensive-regen-done"
TEMP_DIR = Path("/tmp/s3_backfill")
MIN_SESSIONS_FOR_COMPLETE_BACKFILL = 1000


def _backfill_process_running() -> bool:
    try:
        r = subprocess.run(
            ["pgrep", "-f", "import_s3_history_v2"],
            capture_output=True, text=True, timeout=10,
        )
        return r.returncode == 0 and r.stdout.strip() != ""
    except Exception:
        return True  # be safe — assume running if we can't check


def _temp_dir_empty() -> bool:
    if not TEMP_DIR.exists():
        return True
    try:
        return not any(TEMP_DIR.iterdir())
    except Exception:
        return False


def _session_count() -> int:
    db = SessionLocal()
    try:
        return int(db.execute(select(func.count(TelemetrySession.id))).scalar() or 0)
    finally:
        db.close()


def _run(cmd: list[str], timeout: int = 1800) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr)[-4000:]
    except Exception as exc:
        return 99, str(exc)


def main() -> int:
    status = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "backfill_process_running": None,
        "temp_dir_empty": None,
        "session_count": None,
        "eligible_to_regen": False,
        "already_done": FLAG_FILE.exists(),
        "actions": [],
    }

    if FLAG_FILE.exists():
        print(json.dumps({**status, "skipped": "flag_file_present"}, indent=2))
        return 0

    proc_running = _backfill_process_running()
    temp_empty = _temp_dir_empty()
    sessions = _session_count()
    status["backfill_process_running"] = proc_running
    status["temp_dir_empty"] = temp_empty
    status["session_count"] = sessions

    eligible = (not proc_running) and temp_empty and sessions >= MIN_SESSIONS_FOR_COMPLETE_BACKFILL
    status["eligible_to_regen"] = eligible
    if not eligible:
        print(json.dumps(status, indent=2))
        return 0

    # Kick off work. Use the .venv python so env matches.
    py = Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"
    scripts_dir = Path(__file__).resolve().parent

    # 1) Regenerate comprehensive telemetry report (force overwrites today's).
    rc, out = _run(
        [str(py), str(scripts_dir / "generate_telemetry_report.py"),
         "--type", "comprehensive", "--force"],
        timeout=1800,
    )
    status["actions"].append({"step": "generate_comprehensive_report", "rc": rc, "output_tail": out[-400:]})

    # 2) Score historical anomalies over the full 2-year window.
    rc2, out2 = _run(
        [str(py), str(scripts_dir / "detect_telemetry_anomalies.py"),
         "--backfill-from", "2024-01-01"],
        timeout=1800,
    )
    status["actions"].append({"step": "backfill_anomalies", "rc": rc2, "output_tail": out2[-400:]})

    # 3) Email the newly regenerated report to Joseph.
    rc3, out3 = _run(
        [str(py), str(scripts_dir / "email_telemetry_report.py"),
         "--type", "comprehensive"],
        timeout=300,
    )
    status["actions"].append({"step": "email_comprehensive_report", "rc": rc3, "output_tail": out3[-400:]})

    # Mark done so future timer runs no-op.
    try:
        FLAG_DIR.mkdir(parents=True, exist_ok=True)
        FLAG_FILE.write_text(status["checked_at"] + "\n")
        status["flag_file_written"] = str(FLAG_FILE)
    except Exception as exc:
        status["flag_file_write_error"] = str(exc)

    print(json.dumps(status, indent=2))
    # Exit 0 even on partial failure so systemd doesn't spam OnFailure DMs
    # for something that's already logged and flagged.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
