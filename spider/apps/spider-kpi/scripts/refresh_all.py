#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path("/home/jpruit20/.openclaw/workspace/spider-kpi")
SCRIPTS_DIR = BASE_DIR / "scripts"


def run_step(name: str, script_name: str) -> None:
    script_path = SCRIPTS_DIR / script_name
    if not script_path.exists():
        print(f"[skip] {name}: missing {script_name}")
        return

    print(f"[run] {name}: {script_name}")
    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(BASE_DIR),
        text=True,
        capture_output=True,
    )

    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)

    if result.returncode != 0:
        raise RuntimeError(f"Step failed: {name}")


def main() -> int:
    run_step("Shopify ingest", "shopify_ingest_clean.py")
    run_step("Triple Whale ingest", "triplewhale_ingest.py")
    run_step("KPI compute", "kpi_compute.py")
    print("[ok] refresh complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
