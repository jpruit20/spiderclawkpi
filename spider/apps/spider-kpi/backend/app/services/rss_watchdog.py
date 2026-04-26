"""Lightweight RSS watchdog for the FastAPI backend process.

Background daemon thread that polls process RSS every 60 s and writes
one log line per tick. Cheap (a single ``getrusage`` call). Gives us
a continuous record in the spider-kpi journal so we can SEE memory
drift instead of guessing — useful for the ongoing OOM hunt where we
want to know whether the leak comes back when the warmer is on, and
for verifying that any future fix actually stays bounded over hours.

If env var ``SPIDER_KPI_TRACEMALLOC=1`` is set, the watchdog also
runs ``tracemalloc`` continuously. When RSS crosses
``SPIDER_KPI_RSS_DUMP_MB`` (default 2048 MB) it dumps the top
allocation sites to ``/var/log/spider-kpi-rss-dump-{ts}.txt`` once
per dump-threshold crossing. That gives us a forensic snapshot if a
runaway allocation happens in the live process — the boot warmup is
still on, and a future re-enabled interval refresh would auto-trip
this watchdog before it gets OOM-killed.

Tracemalloc has ~10-25% allocator overhead, so it stays opt-in. The
plain RSS log is always on.
"""
from __future__ import annotations

import logging
import os
import resource
import threading
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


_started = False
_lock = threading.Lock()


def _rss_mb() -> float:
    """Current RSS via /proc/self/status (VmRSS).

    NOTE: ``getrusage(RUSAGE_SELF).ru_maxrss`` is HIGH-WATER-MARK, not
    current — it never decreases over the process's lifetime. That
    silently masked memory-release behavior in the 2026-04-25 OOM
    investigation: we couldn't tell if a fix actually freed memory
    or just held the same peak. /proc/self/status/VmRSS gives true
    current RSS so we can SEE memory come back down after a call.
    """
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return float(line.split()[1]) / 1024.0  # KB → MB
    except OSError:
        pass
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def _bool_env(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int_env(name: str, default: int) -> int:
    v = os.environ.get(name)
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _fmt_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _dump_tracemalloc(reason: str, top: int = 30) -> str | None:
    """Write top allocation sites to a timestamped log file. Returns the path."""
    if not tracemalloc.is_tracing():
        return None
    try:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        candidates = [
            Path(f"/var/log/spider-kpi-rss-dump-{ts}.txt"),
            Path(f"/tmp/spider-kpi-rss-dump-{ts}.txt"),
        ]
        snap = tracemalloc.take_snapshot()
        lines = [
            f"=== RSS watchdog dump @ {ts} ({reason}) ===",
            f"rss={_rss_mb():.0f} MB",
            f"top {top} allocations by size:",
        ]
        for stat in snap.statistics("lineno")[:top]:
            lines.append(f"  {_fmt_size(stat.size)} ({stat.count} blocks)")
            for frame in stat.traceback:
                marker = "*" if "/site-packages/" not in frame.filename else " "
                lines.append(f"      {marker} {frame.filename}:{frame.lineno}")
        body = "\n".join(lines) + "\n"
        for path in candidates:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body)
                return str(path)
            except (PermissionError, OSError):
                continue
    except Exception:
        logger.exception("rss_watchdog: tracemalloc dump failed")
    return None


def _watchdog_loop(
    interval_s: float,
    dump_threshold_mb: int,
    tracemalloc_on: bool,
) -> None:
    last_dump_band = -1  # so we dump at most once per "band crossed"
    band_size_mb = max(256, dump_threshold_mb // 2)

    while True:
        try:
            rss = _rss_mb()
            band = int(rss / band_size_mb)
            if tracemalloc_on and rss >= dump_threshold_mb and band > last_dump_band:
                path = _dump_tracemalloc(reason=f"rss>={dump_threshold_mb}MB", top=30)
                if path:
                    logger.warning("rss_watchdog: rss=%.0f MB — dumped tracemalloc to %s", rss, path)
                last_dump_band = band
            # Log at WARNING so the OOM-hunt log shows up in journals
            # whose root level is WARNING (most prod configs). Cheap.
            logger.warning("rss_watchdog: rss=%.0f MB%s", rss, " (tracemalloc on)" if tracemalloc_on else "")
        except Exception:
            # Never let the watchdog kill itself — keep ticking.
            logger.exception("rss_watchdog tick failed")
        time.sleep(interval_s)


def start_rss_watchdog() -> None:
    """Idempotent: starts the watchdog thread once per process.

    Reads config from env:
      SPIDER_KPI_RSS_INTERVAL_S    (default 60)
      SPIDER_KPI_TRACEMALLOC       (default 0; 1 = on)
      SPIDER_KPI_TRACEMALLOC_FRAMES (default 15)
      SPIDER_KPI_RSS_DUMP_MB       (default 2048; only used if tracemalloc on)
    """
    global _started
    with _lock:
        if _started:
            return
        _started = True

    interval = _int_env("SPIDER_KPI_RSS_INTERVAL_S", 60)
    tracemalloc_on = _bool_env("SPIDER_KPI_TRACEMALLOC", False)
    tracemalloc_frames = _int_env("SPIDER_KPI_TRACEMALLOC_FRAMES", 15)
    dump_threshold = _int_env("SPIDER_KPI_RSS_DUMP_MB", 2048)

    if tracemalloc_on and not tracemalloc.is_tracing():
        try:
            tracemalloc.start(tracemalloc_frames)
            logger.warning(
                "rss_watchdog: tracemalloc enabled (frames=%d, dump@%dMB)",
                tracemalloc_frames, dump_threshold,
            )
        except Exception:
            logger.exception("rss_watchdog: failed to start tracemalloc — continuing without")
            tracemalloc_on = False

    t = threading.Thread(
        target=_watchdog_loop,
        args=(interval, dump_threshold, tracemalloc_on),
        name="rss-watchdog",
        daemon=True,
    )
    t.start()
    logger.warning(
        "rss_watchdog: started (interval=%ds, tracemalloc=%s)",
        interval, "on" if tracemalloc_on else "off",
    )
