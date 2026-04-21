"""Cook-behavior baselines — per (target_temp_band, firmware_version) stats
on how cooks actually progress.

This is the knowledge-base core:

  * ramp_time_seconds — how long from engage to within ±15°F of target.
  * steady_state_fan_intensity — typical fan % after reach.
  * steady_state_temp_stddev — how tightly the PID holds.
  * cool_down_rate_f_per_min — how fast a grill cools after disengage.
  * typical_duration_seconds — how long cooks last.
  * session_count — how many sessions contributed to this bin.

The state classifier (``cook_state_classifier.py``) consumes these via
``get_baseline_lookup`` to replace its Phase 1 heuristic ramp budgets
with actual learned percentiles.

Rebuilt nightly by ``rebuild_cook_behavior_baselines`` from the
``telemetry_sessions`` table.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median, pstdev
from typing import Any, Callable, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import CookBehaviorBaseline, TelemetrySession


# ── target-temp bands ───────────────────────────────────────────────────

# 50°F bands from 150°F to 700°F. Band label is the inclusive lower
# bound (so 250..299 is band "250"). Anything outside is "other".
BAND_WIDTH = 50
BAND_MIN = 150
BAND_MAX = 700


def temp_band(target_temp: Optional[float]) -> Optional[str]:
    if target_temp is None:
        return None
    try:
        t = float(target_temp)
    except (TypeError, ValueError):
        return None
    if t < BAND_MIN or t > BAND_MAX + BAND_WIDTH:
        return None
    lo = int((t // BAND_WIDTH) * BAND_WIDTH)
    return str(lo)


def all_bands() -> list[str]:
    return [str(lo) for lo in range(BAND_MIN, BAND_MAX + 1, BAND_WIDTH)]


# ── percentile helpers ──────────────────────────────────────────────────

def _pct(values: list[float], q: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(float(ordered[0]), 2)
    idx = (len(ordered) - 1) * q
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    frac = idx - lo
    return round(float(ordered[lo]) + (float(ordered[hi]) - float(ordered[lo])) * frac, 2)


# ── observation extraction ──────────────────────────────────────────────

@dataclass
class _Observation:
    band: str
    firmware: Optional[str]
    ramp_time_seconds: Optional[int]
    steady_fan_intensity: Optional[float]
    steady_temp_stddev: Optional[float]
    cool_down_rate_f_per_min: Optional[float]
    typical_duration_seconds: Optional[int]


def _extract_observation(s: TelemetrySession) -> Optional[_Observation]:
    """Pull the six metrics for one session. Returns None if not
    scorable (no target temp, no time series, etc.)."""
    band = temp_band(s.target_temp)
    if band is None:
        return None
    target = float(s.target_temp)
    series = s.actual_temp_time_series or []
    if not series:
        return None
    # Parse series points once.
    pts: list[tuple[datetime, float]] = []
    for p in series:
        if not isinstance(p, dict):
            continue
        ts = p.get("t")
        c = p.get("c")
        if ts is None or c is None:
            continue
        try:
            if isinstance(ts, str):
                ts = ts[:-1] + "+00:00" if ts.endswith("Z") else ts
                tsd = datetime.fromisoformat(ts)
            elif isinstance(ts, datetime):
                tsd = ts
            else:
                continue
            temp_f = float(c)
        except Exception:
            continue
        pts.append((tsd, temp_f))
    if not pts:
        return None

    # Ramp time: first point where temp within ±15°F of target, measured
    # from session_start (or first sample).
    start_ts = s.session_start or pts[0][0]
    ramp_s: Optional[int] = None
    reach_idx: Optional[int] = None
    for i, (ts, t) in enumerate(pts):
        if abs(t - target) <= 15.0:
            ramp_s = int((ts - start_ts).total_seconds())
            reach_idx = i
            break
    # Fan intensity + temp stddev over post-reach window.
    steady_fan: Optional[float] = None
    steady_std: Optional[float] = None
    if reach_idx is not None and len(pts) - reach_idx >= 6:
        post_temps = [t for (_, t) in pts[reach_idx:]]
        if len(post_temps) >= 2:
            try:
                steady_std = round(pstdev(post_temps), 2)
            except Exception:
                steady_std = None
        fan_series = s.fan_output_time_series or []
        fan_vals: list[float] = []
        reach_ts = pts[reach_idx][0]
        for fp in fan_series:
            if not isinstance(fp, dict):
                continue
            fts = fp.get("ts")
            v = fp.get("value")
            if fts is None or v is None:
                continue
            try:
                if isinstance(fts, str):
                    fts = fts[:-1] + "+00:00" if fts.endswith("Z") else fts
                    ftsd = datetime.fromisoformat(fts)
                elif isinstance(fts, datetime):
                    ftsd = fts
                else:
                    continue
                fv = float(v)
            except Exception:
                continue
            if ftsd >= reach_ts:
                fan_vals.append(fv)
        if fan_vals:
            steady_fan = round(sum(fan_vals) / len(fan_vals), 2)
    # Cool-down rate: tail of curve, temp dropping. Take last 10 post-reach
    # samples where temp is monotone-decreasing for a reasonable signal.
    cool_rate: Optional[float] = None
    if reach_idx is not None and len(pts) - reach_idx >= 4:
        tail = pts[-min(10, len(pts)):]
        if len(tail) >= 4:
            t0_ts, t0_t = tail[0]
            tl_ts, tl_t = tail[-1]
            dt_min = (tl_ts - t0_ts).total_seconds() / 60.0
            if dt_min > 0 and tl_t < t0_t:
                cool_rate = round((t0_t - tl_t) / dt_min, 2)

    dur = s.session_duration_seconds
    return _Observation(
        band=band,
        firmware=s.firmware_version,
        ramp_time_seconds=ramp_s,
        steady_fan_intensity=steady_fan,
        steady_temp_stddev=steady_std,
        cool_down_rate_f_per_min=cool_rate,
        typical_duration_seconds=dur if isinstance(dur, int) and dur > 0 else None,
    )


# ── baseline rebuild ────────────────────────────────────────────────────

MIN_SAMPLES_PER_BIN = 3           # below this the bin stats aren't meaningful
DEFAULT_BASELINE_VERSION = 1      # bumped when the rebuild logic changes


def rebuild_cook_behavior_baselines(
    db: Session,
    *,
    include_firmware_splits: bool = True,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Nightly: scan telemetry_sessions, bin by (band, firmware), compute
    percentile stats, upsert into cook_behavior_baselines.

    Also writes an "all firmware" rollup row per band
    (firmware_version=NULL) so the classifier always has a baseline
    even for firmware versions with too few samples.
    """
    now = now or datetime.now(timezone.utc)

    sessions = db.execute(
        select(TelemetrySession)
        .where(TelemetrySession.target_temp.is_not(None))
        .where(TelemetrySession.target_temp > 0)
    ).scalars().all()

    # Bucket: (band, firmware_or_NONE) -> list[_Observation]
    by_bin: dict[tuple[str, Optional[str]], list[_Observation]] = defaultdict(list)
    for s in sessions:
        obs = _extract_observation(s)
        if obs is None:
            continue
        # Always add to the "all firmware" roll-up.
        by_bin[(obs.band, None)].append(obs)
        # And to the firmware-specific bin.
        if include_firmware_splits and obs.firmware:
            by_bin[(obs.band, obs.firmware)].append(obs)

    # Clear existing rows and rewrite — simpler than upsert logic, rebuild
    # is small (bands × firmware versions ≈ a few hundred rows).
    db.execute(delete(CookBehaviorBaseline))

    written = 0
    for (band, firmware), obs_list in by_bin.items():
        if len(obs_list) < MIN_SAMPLES_PER_BIN:
            continue
        ramp_vals = [o.ramp_time_seconds for o in obs_list if o.ramp_time_seconds is not None]
        fan_vals = [o.steady_fan_intensity for o in obs_list if o.steady_fan_intensity is not None]
        std_vals = [o.steady_temp_stddev for o in obs_list if o.steady_temp_stddev is not None]
        cool_vals = [o.cool_down_rate_f_per_min for o in obs_list if o.cool_down_rate_f_per_min is not None]
        dur_vals = [o.typical_duration_seconds for o in obs_list if o.typical_duration_seconds is not None]

        row = CookBehaviorBaseline(
            target_temp_band=band,
            firmware_version=firmware,
            sample_size=len(obs_list),
            ramp_time_p10=_pct([float(v) for v in ramp_vals], 0.10),
            ramp_time_p50=_pct([float(v) for v in ramp_vals], 0.50),
            ramp_time_p90=_pct([float(v) for v in ramp_vals], 0.90),
            steady_fan_p10=_pct(fan_vals, 0.10),
            steady_fan_p50=_pct(fan_vals, 0.50),
            steady_fan_p90=_pct(fan_vals, 0.90),
            steady_temp_stddev_p50=_pct(std_vals, 0.50),
            steady_temp_stddev_p90=_pct(std_vals, 0.90),
            cool_down_rate_p50=_pct(cool_vals, 0.50),
            typical_duration_p50=_pct([float(v) for v in dur_vals], 0.50),
            baseline_version=DEFAULT_BASELINE_VERSION,
            computed_at=now,
        )
        db.add(row)
        written += 1
    db.flush()
    db.commit()
    return {
        "bins_written": written,
        "total_sessions_scanned": len(sessions),
        "computed_at": now.isoformat(),
    }


# ── lookup helper consumed by the classifier ────────────────────────────

def get_baseline_lookup(db: Session) -> Callable[[float, Optional[str]], Optional[dict[str, Any]]]:
    """Return a callable the classifier can call per event.

    Preloads every baseline row into an in-memory map so classifying an
    entire fleet snapshot stays O(1) per device.

    Lookup order: (band, firmware) → (band, None) → None.
    """
    rows = db.execute(select(CookBehaviorBaseline)).scalars().all()
    index: dict[tuple[str, Optional[str]], CookBehaviorBaseline] = {}
    for r in rows:
        index[(r.target_temp_band, r.firmware_version)] = r

    def _lookup(target_temp: float, firmware_version: Optional[str]) -> Optional[dict[str, Any]]:
        band = temp_band(target_temp)
        if band is None:
            return None
        row = index.get((band, firmware_version)) or index.get((band, None))
        if row is None:
            return None
        # Classifier cares about: ramp_budget_seconds + post_reach_tolerance_f.
        # Use p90 of ramp (conservative — leaves headroom for slower-than-
        # typical starts). Tolerance = max(15, p90 steady_temp_stddev × 2).
        ramp_budget = int(row.ramp_time_p90) if row.ramp_time_p90 else None
        tolerance = None
        if row.steady_temp_stddev_p90 is not None:
            tolerance = max(15.0, float(row.steady_temp_stddev_p90) * 2)
        return {
            "ramp_budget_seconds": ramp_budget,
            "post_reach_tolerance_f": tolerance,
            "band": band,
            "sample_size": row.sample_size,
            "baseline_version": row.baseline_version,
        }

    return _lookup
