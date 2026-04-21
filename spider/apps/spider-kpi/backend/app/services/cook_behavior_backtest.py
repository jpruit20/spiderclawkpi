"""Self-evaluation: given the CURRENT cook_behavior_baselines and the
sessions that have arrived since they were computed, how well do the
baseline p10-p90 bands actually contain new data?

Run nightly BEFORE ``rebuild_cook_behavior_baselines`` so we're always
scoring the version that was in production yesterday against the
reality that showed up overnight.

For each (target_temp_band, metric), we compute:

  * in_band_count  — sessions whose actual value fell inside p10..p90
  * below_band_count / above_band_count
  * coverage_pct    — in_band_count / sample_size (targeting ~0.80)
  * median_error_pct — median of |actual - p50| / p50

A baseline is "healthy" when coverage_pct is close to 0.80 (by
construction of p10/p90) and median_error_pct is low. Drift shows up
as coverage << 80% — either the fleet changed (new firmware, new user
mix) or the bands are too tight.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CookBehaviorBacktest, CookBehaviorBaseline, TelemetrySession
from app.services.cook_behavior_baselines import _extract_observation, temp_band


_METRICS = [
    ("ramp_time", "ramp_time_seconds"),
    ("steady_fan", "steady_fan_intensity"),
    ("steady_temp_stddev", "steady_temp_stddev"),
]


def run_cook_behavior_backtest(
    db: Session,
    *,
    lookback_days: int = 2,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Score the CURRENT baselines (firmware_version=NULL rollup rows
    only — firmware splits can have too-few samples to be meaningful) on
    the last ``lookback_days`` of sessions."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=lookback_days)

    # Load rollup baselines indexed by band.
    rollups: dict[str, CookBehaviorBaseline] = {}
    for b in db.execute(
        select(CookBehaviorBaseline).where(CookBehaviorBaseline.firmware_version.is_(None))
    ).scalars().all():
        rollups[b.target_temp_band] = b

    if not rollups:
        return {"skipped": True, "reason": "no baselines yet"}

    sessions = db.execute(
        select(TelemetrySession)
        .where(TelemetrySession.target_temp.is_not(None))
        .where(TelemetrySession.target_temp > 0)
        .where(TelemetrySession.session_end.is_not(None))
        .where(TelemetrySession.session_end >= cutoff)
    ).scalars().all()

    # Per (band, metric) -> list of actual values
    buckets: dict[tuple[str, str], list[float]] = {}
    for s in sessions:
        obs = _extract_observation(s)
        if obs is None:
            continue
        for metric_name, attr in _METRICS:
            v = getattr(obs, attr, None)
            if v is None:
                continue
            buckets.setdefault((obs.band, metric_name), []).append(float(v))

    written = 0
    for (band, metric_name), vals in buckets.items():
        base = rollups.get(band)
        if base is None:
            continue
        # Pick the right p10/p50/p90 triple.
        if metric_name == "ramp_time":
            p10, p50, p90 = base.ramp_time_p10, base.ramp_time_p50, base.ramp_time_p90
        elif metric_name == "steady_fan":
            p10, p50, p90 = base.steady_fan_p10, base.steady_fan_p50, base.steady_fan_p90
        else:
            # steady_temp_stddev only has p50/p90 in the baseline; use p50 as lower and p90 as upper band estimate.
            p10, p50, p90 = None, base.steady_temp_stddev_p50, base.steady_temp_stddev_p90
        if p50 is None:
            continue

        in_band = below = above = 0
        errs: list[float] = []
        for v in vals:
            lo = p10 if p10 is not None else None
            hi = p90 if p90 is not None else None
            if lo is not None and v < lo:
                below += 1
            elif hi is not None and v > hi:
                above += 1
            elif lo is not None and hi is not None:
                in_band += 1
            else:
                # Can't classify without both bounds; treat as in-band.
                in_band += 1
            if p50 and p50 > 0:
                errs.append(abs(v - p50) / p50)

        coverage = round(in_band / len(vals), 4) if vals else None
        med_err = round(median(errs), 4) if errs else None

        db.add(CookBehaviorBacktest(
            run_at=now,
            baseline_version=base.baseline_version,
            target_temp_band=band,
            metric=metric_name,
            sample_size=len(vals),
            in_band_count=in_band,
            below_band_count=below,
            above_band_count=above,
            coverage_pct=coverage,
            median_error_pct=med_err,
        ))
        written += 1
    db.commit()
    return {
        "rows_written": written,
        "sessions_scored": len(sessions),
        "run_at": now.isoformat(),
    }


def load_latest_drift(db: Session, *, limit_bands: int = 30) -> list[dict[str, Any]]:
    """Fetch the most recent backtest run's rows (for surfacing drift in
    the UI)."""
    # Latest run_at
    latest = db.execute(
        select(CookBehaviorBacktest.run_at)
        .order_by(CookBehaviorBacktest.run_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest is None:
        return []
    rows = db.execute(
        select(CookBehaviorBacktest)
        .where(CookBehaviorBacktest.run_at == latest)
        .order_by(CookBehaviorBacktest.target_temp_band, CookBehaviorBacktest.metric)
        .limit(limit_bands * 3)
    ).scalars().all()
    return [{
        "run_at": r.run_at.isoformat() if r.run_at else None,
        "baseline_version": r.baseline_version,
        "target_temp_band": r.target_temp_band,
        "metric": r.metric,
        "sample_size": r.sample_size,
        "coverage_pct": r.coverage_pct,
        "median_error_pct": r.median_error_pct,
        "in_band_count": r.in_band_count,
        "below_band_count": r.below_band_count,
        "above_band_count": r.above_band_count,
    } for r in rows]
