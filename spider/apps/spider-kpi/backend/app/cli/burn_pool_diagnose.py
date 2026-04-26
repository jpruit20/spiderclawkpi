"""One-shot tracemalloc + RSS profiler for ``_build_device_burn_pool``.

The 4-min cohort burn pool refresh job has been OOM-killing the
backend on the 4 GB droplet (~165 SIGKILLs/day, 7-10 min cadence)
since 2026-04-18. The earlier "shrink Python row count + malloc_trim"
fix (94f07d8) did NOT solve it — so a single ``_build_device_burn_pool``
call allocates GB of memory somewhere we haven't located yet. The
4-min interval is currently disabled; this script lets us run ONE
cold call under tracemalloc and get a top-N allocation report so the
next fix is grounded in measurement, not theory.

USAGE (on the droplet):

    cd /opt/spiderclawkpi/spider/apps/spider-kpi
    sudo -u root .venv/bin/python -m app.cli.burn_pool_diagnose --lookback 90

Args:
    --lookback {90,180,both}  which lookback window to profile (default: 90)
    --top N                   how many allocation sites to dump (default: 30)
    --snapshot-every S        sampling interval in seconds (default: 5.0)
    --output PATH             where to write the report (default:
                              /var/log/spider-kpi-burn-pool-diag-{ts}.txt)

What it captures:
    - Baseline RSS before any work
    - Per-snapshot RSS during the call (every --snapshot-every seconds)
    - tracemalloc top-N allocations at peak RSS
    - tracemalloc diff (after - before) so we see what GREW
    - Total elapsed time and final pool size

Caveats:
    tracemalloc only sees Python-level allocations. If the leak is
    inside libpq / psycopg2 / a C extension, tracemalloc will show
    little growth even as RSS climbs to GB. That itself is a strong
    diagnostic signal — points us at the C side.

    Running this script on the live droplet allocates the same GB the
    OOM-killed warmer did. It WILL likely OOM-kill itself near the
    peak. The periodic snapshots are dumped to disk as we go, so we
    keep the timeline up to the kill point.
"""
from __future__ import annotations

import argparse
import gc
import json
import resource
import sys
import threading
import time
import tracemalloc
import traceback
from datetime import datetime, timezone
from pathlib import Path


def _rss_mb() -> float:
    """Current RSS via /proc/self/status (VmRSS).

    Falls back to ``getrusage`` ru_maxrss (high-water-mark) if /proc
    isn't readable. The first run of this tool used ru_maxrss and we
    couldn't tell if memory came back down between iterations — the
    answer to "did the fix work?" requires CURRENT RSS, not peak.
    """
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return float(line.split()[1]) / 1024.0  # KB → MB
    except OSError:
        pass
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def _fmt_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:7.1f} {unit}"
        n /= 1024
    return f"{n:7.1f} TB"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _format_traceback(tb) -> str:
    """tracemalloc Traceback → readable multi-line string, app frames first."""
    lines = []
    for frame in tb:
        # Highlight app code over site-packages
        marker = "*" if "/site-packages/" not in frame.filename else " "
        lines.append(f"      {marker} {frame.filename}:{frame.lineno}")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--lookback", default="90", choices=["90", "180", "both"])
    p.add_argument("--top", type=int, default=30)
    p.add_argument("--snapshot-every", type=float, default=5.0)
    p.add_argument("--output", default=None)
    p.add_argument("--frames", type=int, default=25, help="tracemalloc frame depth")
    args = p.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_path = Path(args.output) if args.output else Path(
        f"/var/log/spider-kpi-burn-pool-diag-{ts}.txt"
    )
    # If we can't write to /var/log (e.g. running as a non-root dev),
    # fall back to /tmp so the script doesn't fail before doing real work.
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.touch()
    except (PermissionError, OSError):
        out_path = Path(f"/tmp/spider-kpi-burn-pool-diag-{ts}.txt")
        out_path.parent.mkdir(parents=True, exist_ok=True)

    log_lines: list[str] = []

    def log(msg: str) -> None:
        line = f"[{_now()}] {msg}"
        print(line, flush=True)
        log_lines.append(line)
        # Persist incrementally so we don't lose the timeline if we
        # OOM-kill ourselves at peak.
        try:
            out_path.write_text("\n".join(log_lines) + "\n")
        except OSError:
            pass

    log("=== burn pool tracemalloc diagnostic ===")
    log(f"output    : {out_path}")
    log(f"lookback  : {args.lookback}")
    log(f"top N     : {args.top}")
    log(f"sample    : every {args.snapshot_every}s")
    log(f"frames    : {args.frames}")
    log(f"baseline  : rss={_rss_mb():.0f} MB")

    tracemalloc.start(args.frames)

    snapshots: list[tuple[float, float, tracemalloc.Snapshot]] = []
    stop_evt = threading.Event()

    def sampler() -> None:
        t0 = time.monotonic()
        while not stop_evt.wait(args.snapshot_every):
            try:
                elapsed = time.monotonic() - t0
                rss = _rss_mb()
                snap = tracemalloc.take_snapshot()
                snapshots.append((elapsed, rss, snap))
                top = snap.statistics("lineno")[:5]
                top_str = ", ".join(
                    f"{Path(s.traceback[0].filename).name}:{s.traceback[0].lineno}={_fmt_size(s.size).strip()}"
                    for s in top
                )
                log(f"  +{elapsed:5.1f}s rss={rss:6.0f} MB  top5: {top_str}")
            except Exception as e:
                log(f"  sampler error: {type(e).__name__}: {e}")

    sampler_thread = threading.Thread(target=sampler, daemon=True)
    sampler_thread.start()

    # Imports are intentionally lazy — we want the tracemalloc baseline
    # snapshot to NOT include the cost of pulling in the app graph.
    log("importing app modules ...")
    from app.db.session import SessionLocal
    from app.services.charcoal_jit import _build_device_burn_pool

    rss_after_imports = _rss_mb()
    snap_baseline = tracemalloc.take_snapshot()
    log(f"after imports: rss={rss_after_imports:.0f} MB")

    targets = [90, 180] if args.lookback == "both" else [int(args.lookback)]
    now = datetime.now(timezone.utc)

    per_call: list[dict] = []
    for lb in targets:
        log(f"--- _build_device_burn_pool(lookback_days={lb}, force=True)")
        rss0 = _rss_mb()
        t_call = time.monotonic()
        db = SessionLocal()
        outcome: dict = {"lookback": lb, "rss_start_mb": rss0}
        try:
            pool = _build_device_burn_pool(db, lookback_days=lb, now=now, force=True)
            duration = time.monotonic() - t_call
            outcome["devices"] = len(pool)
            outcome["duration_s"] = round(duration, 2)
            outcome["rss_end_mb"] = _rss_mb()
            outcome["rss_delta_mb"] = round(outcome["rss_end_mb"] - rss0, 1)
            log(
                f"  ok: {len(pool)} devices in {duration:.1f}s, "
                f"rss {rss0:.0f}->{outcome['rss_end_mb']:.0f} MB "
                f"(Δ {outcome['rss_delta_mb']:+.0f})"
            )
        except Exception as e:
            outcome["error"] = f"{type(e).__name__}: {e}"
            outcome["traceback"] = traceback.format_exc()
            outcome["rss_end_mb"] = _rss_mb()
            log(f"  FAILED: {outcome['error']}")
            log(outcome["traceback"])
        finally:
            try:
                db.close()
            except Exception:
                pass
        per_call.append(outcome)

        # Force a GC + arena trim between iterations so we can see
        # whether the leak is per-call (RSS resets) or accumulating
        # (RSS stays high).
        gc.collect()
        try:
            import ctypes
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except OSError:
            pass
        log(f"  after gc+trim: rss={_rss_mb():.0f} MB")

    # Final snapshots
    snap_final = tracemalloc.take_snapshot()
    rss_final = _rss_mb()
    stop_evt.set()
    sampler_thread.join(timeout=2)

    log("")
    log(f"=== final RSS: {rss_final:.0f} MB ===")

    log("")
    log(f"=== diff (final - after_imports), top {args.top} by size_diff ===")
    diff = snap_final.compare_to(snap_baseline, "lineno")
    for stat in diff[: args.top]:
        log(f"  {_fmt_size(stat.size_diff)} ({stat.count_diff:+d} blocks)")
        log(_format_traceback(stat.traceback))

    log("")
    log(f"=== final top {args.top} by current size ===")
    for stat in snap_final.statistics("lineno")[: args.top]:
        log(f"  {_fmt_size(stat.size)} ({stat.count} blocks)")
        log(_format_traceback(stat.traceback))

    if snapshots:
        peak_elapsed, peak_rss, peak_snap = max(snapshots, key=lambda s: s[1])
        log("")
        log(f"=== peak snapshot @ +{peak_elapsed:.1f}s (rss={peak_rss:.0f} MB), top {args.top} ===")
        for stat in peak_snap.statistics("lineno")[: args.top]:
            log(f"  {_fmt_size(stat.size)} ({stat.count} blocks)")
            log(_format_traceback(stat.traceback))

    log("")
    log("=== RSS timeline ===")
    log(f"  baseline    : {rss_after_imports:.0f} MB")
    for elapsed, r, _ in snapshots:
        log(f"  +{elapsed:5.1f}s  : {r:.0f} MB")
    log(f"  final       : {rss_final:.0f} MB")

    log("")
    log("=== summary JSON ===")
    summary = {
        "ts": ts,
        "lookback": args.lookback,
        "rss_baseline_mb": round(rss_after_imports, 1),
        "rss_peak_mb": round(max((s[1] for s in snapshots), default=rss_final), 1),
        "rss_final_mb": round(rss_final, 1),
        "calls": per_call,
    }
    log(json.dumps(summary, indent=2))

    out_path.write_text("\n".join(log_lines) + "\n")
    log(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
