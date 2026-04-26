"""Entry point invoked by the scheduler's run_syncs() to execute one
full sync sweep in an isolated subprocess.

Why this exists: multiple connectors inside the sync sweep leak
hundreds of MB of C-side memory per call (verified 2026-04-25 via
app.cli.run_syncs_diagnose: aws_telemetry ~815 MB held, materialize
~2-3 GB peak, recompute_daily_kpis ~540 MB held). On a 4 GB droplet
that produced a 7-10 min OOM-kill loop. Running this in a fresh
process means the OS reclaims everything when we exit — the
long-lived uvicorn process stays bounded.

Don't import this module from anywhere; it's invoked only by
``run_syncs()`` in ``app.scheduler`` via subprocess.run.
"""
from __future__ import annotations

import logging
import sys


def _configure_logging() -> None:
    # Log to stdout so the parent's subprocess.run captures it.
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def main() -> int:
    _configure_logging()
    log = logging.getLogger("run_syncs_subprocess")
    log.warning("run_syncs subprocess starting")
    try:
        from app.scheduler import _run_syncs_inner
        _run_syncs_inner()
    except Exception:
        log.exception("run_syncs subprocess crashed")
        return 1
    log.warning("run_syncs subprocess complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
