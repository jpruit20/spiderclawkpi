"""One-shot tracemalloc + RSS profiler for individual ``run_syncs`` steps.

After 6e9f5ca disabled the entire ``run_syncs`` interval to stop a
~165-OOM-per-day kill loop, we know the leak lives somewhere inside
that function but not in the cohort burn pool warmer (already fixed
in 33355a2) or in materialize_app_side (already skipped in 7ffb7a8).
This tool runs ONE step at a time in isolation, with tracemalloc
capturing peak RSS + top allocation sites, so we can bisect which
connector is actually the leak.

USAGE (on the droplet):

    cd /opt/spiderclawkpi/spider/apps/spider-kpi/backend
    sudo -u root /opt/spiderclawkpi/spider/apps/spider-kpi/.venv/bin/python \\
        -m app.cli.run_syncs_diagnose --target aws_telemetry

Targets:
    shopify, triplewhale, freshdesk, ga4, aws_telemetry, clarity,
    reddit, amazon, clickup, slack, youtube, youtube_lore,
    cook_rederivation, materialize_app_side,
    recompute_daily_kpis, recompute_diagnostics

Why one-at-a-time + fresh process: the leak grew RSS ~2.6 GB in
60 s during the live OOM. If we ran multiple targets in one process,
the first heavy target would self-OOM before we could measure the
others. One process per target, with the report written
incrementally so we keep the timeline up to the kill point.

Output: /var/log/spider-kpi-runsyncs-diag-{target}-{ts}.txt
        (falls back to /tmp if /var/log isn't writable)
"""
from __future__ import annotations

import argparse
import ctypes
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
from typing import Any, Callable


def _rss_mb() -> float:
    """Current RSS via /proc/self/status (VmRSS, not high-water-mark)."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return float(line.split()[1]) / 1024.0
    except OSError:
        pass
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def _fmt_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:7.1f} {unit}"
        n /= 1024
    return f"{n:7.1f} TB"


def _format_traceback(tb) -> str:
    """tracemalloc Traceback → readable multi-line, app frames marked."""
    lines = []
    for frame in tb:
        marker = "*" if "/site-packages/" not in frame.filename else " "
        lines.append(f"      {marker} {frame.filename}:{frame.lineno}")
    return "\n".join(lines)


def _malloc_trim() -> None:
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except OSError:
        pass


# ── Target registry ──────────────────────────────────────────────────
#
# Each entry returns a callable that takes (db) and runs the work.
# We resolve LAZILY so a missing/broken connector doesn't break the
# diagnostic for unrelated targets.


def _resolve_target(name: str) -> Callable[[Any], Any]:
    if name == "shopify":
        from app.ingestion.connectors.shopify import sync_shopify_orders
        return sync_shopify_orders
    if name == "triplewhale":
        from app.ingestion.connectors.triplewhale import sync_triplewhale
        return lambda db: sync_triplewhale(db, backfill_days=1)
    if name == "freshdesk":
        from app.ingestion.connectors.freshdesk import sync_freshdesk
        return lambda db: sync_freshdesk(db, days=7)
    if name == "ga4":
        from app.ingestion.connectors.ga4 import sync_ga4
        return lambda db: sync_ga4(db, days=7)
    if name == "aws_telemetry":
        from app.ingestion.connectors.aws_telemetry import sync_aws_telemetry
        return sync_aws_telemetry
    if name == "clarity":
        from app.ingestion.connectors.clarity import sync_clarity
        return lambda db: sync_clarity(db, days=1)
    if name == "reddit":
        from app.ingestion.connectors.reddit import sync_reddit
        return sync_reddit
    if name == "amazon":
        from app.ingestion.connectors.amazon import sync_amazon
        return sync_amazon
    if name == "clickup":
        from app.ingestion.connectors.clickup import sync_clickup
        return sync_clickup
    if name == "slack":
        from app.ingestion.connectors.slack import sync_slack
        return sync_slack
    if name == "youtube":
        from app.ingestion.connectors.youtube import sync_youtube
        return sync_youtube
    if name == "youtube_lore":
        from app.ingestion.connectors.youtube_lore import sync_youtube_lore
        return sync_youtube_lore
    if name == "cook_rederivation":
        from app.services.cook_rederivation import run_cook_rederivation
        return run_cook_rederivation
    if name == "materialize_app_side":
        from app.compute.app_side import materialize_app_side
        return materialize_app_side
    if name == "recompute_daily_kpis":
        from app.compute.kpis import recompute_daily_kpis
        return recompute_daily_kpis
    if name == "recompute_diagnostics":
        from app.compute.kpis import recompute_diagnostics
        return recompute_diagnostics
    raise ValueError(f"unknown target: {name}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--target", required=True, help="connector or compute step name")
    p.add_argument("--top", type=int, default=25)
    p.add_argument("--snapshot-every", type=float, default=3.0)
    p.add_argument("--frames", type=int, default=20)
    p.add_argument("--output", default=None)
    args = p.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_path = Path(args.output) if args.output else Path(
        f"/var/log/spider-kpi-runsyncs-diag-{args.target}-{ts}.txt"
    )
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.touch()
    except (PermissionError, OSError):
        out_path = Path(f"/tmp/spider-kpi-runsyncs-diag-{args.target}-{ts}.txt")
        out_path.parent.mkdir(parents=True, exist_ok=True)

    log_lines: list[str] = []

    def log(msg: str) -> None:
        line = f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {msg}"
        print(line, flush=True)
        log_lines.append(line)
        try:
            out_path.write_text("\n".join(log_lines) + "\n")
        except OSError:
            pass

    log(f"=== run_syncs step diagnostic: {args.target} ===")
    log(f"output    : {out_path}")
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
                top = snap.statistics("lineno")[:3]
                top_str = ", ".join(
                    f"{Path(s.traceback[0].filename).name}:{s.traceback[0].lineno}={_fmt_size(s.size).strip()}"
                    for s in top
                )
                log(f"  +{elapsed:5.1f}s rss={rss:6.0f} MB  top3: {top_str}")
            except Exception as e:
                log(f"  sampler error: {type(e).__name__}: {e}")

    sampler_thread = threading.Thread(target=sampler, daemon=True)
    sampler_thread.start()

    # Lazy imports + target resolution AFTER tracemalloc starts but
    # BEFORE we mark the baseline snapshot, so import allocations
    # don't pollute the diff but we still see them.
    log("resolving target ...")
    try:
        target_fn = _resolve_target(args.target)
    except Exception as e:
        log(f"FAILED to resolve target: {e}")
        log(traceback.format_exc())
        return 2

    from app.db.session import SessionLocal

    rss_after_imports = _rss_mb()
    snap_baseline = tracemalloc.take_snapshot()
    log(f"after imports: rss={rss_after_imports:.0f} MB")

    log(f"--- running {args.target}(db) ...")
    rss_call_start = _rss_mb()
    t_call = time.monotonic()
    db = SessionLocal()
    outcome: dict[str, Any] = {"target": args.target, "rss_start_mb": rss_call_start}
    try:
        result = target_fn(db)
        duration = time.monotonic() - t_call
        outcome["duration_s"] = round(duration, 2)
        outcome["rss_end_mb"] = _rss_mb()
        outcome["rss_delta_mb"] = round(outcome["rss_end_mb"] - rss_call_start, 1)
        try:
            outcome["result"] = (
                str(result)[:500] if not isinstance(result, dict) else
                {k: v for k, v in result.items() if isinstance(v, (int, float, bool, str)) or v is None}
            )
        except Exception:
            outcome["result"] = "<unrepr-able>"
        log(
            f"  ok in {duration:.1f}s, rss "
            f"{rss_call_start:.0f} -> {outcome['rss_end_mb']:.0f} MB "
            f"(delta {outcome['rss_delta_mb']:+.0f})"
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

    rss_after_close = _rss_mb()
    log(f"after db.close(): rss={rss_after_close:.0f} MB")

    gc.collect()
    _malloc_trim()
    rss_after_trim = _rss_mb()
    log(f"after gc + malloc_trim: rss={rss_after_trim:.0f} MB")

    snap_final = tracemalloc.take_snapshot()
    rss_final = _rss_mb()
    stop_evt.set()
    sampler_thread.join(timeout=2)

    log("")
    log(f"=== diff (final - after_imports), top {args.top} by size_diff ===")
    for stat in snap_final.compare_to(snap_baseline, "lineno")[: args.top]:
        log(f"  {_fmt_size(stat.size_diff)} ({stat.count_diff:+d} blocks)")
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
    log(f"  baseline       : {rss_after_imports:.0f} MB")
    for elapsed, r, _ in snapshots:
        log(f"  +{elapsed:5.1f}s     : {r:.0f} MB")
    log(f"  after close    : {rss_after_close:.0f} MB")
    log(f"  after gc+trim  : {rss_after_trim:.0f} MB")
    log(f"  final          : {rss_final:.0f} MB")

    log("")
    log("=== summary JSON ===")
    summary = {
        "ts": ts,
        "target": args.target,
        "rss_baseline_mb": round(rss_after_imports, 1),
        "rss_peak_mb": round(max((s[1] for s in snapshots), default=rss_final), 1),
        "rss_after_close_mb": round(rss_after_close, 1),
        "rss_after_trim_mb": round(rss_after_trim, 1),
        "rss_held_after_trim_mb": round(rss_after_trim - rss_after_imports, 1),
        "outcome": outcome,
    }
    log(json.dumps(summary, indent=2, default=str))

    out_path.write_text("\n".join(log_lines) + "\n")
    log(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
