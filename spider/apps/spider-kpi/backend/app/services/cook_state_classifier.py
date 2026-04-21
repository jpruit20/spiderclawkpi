"""Time-aware, baseline-aware classification of a grill's current cook state.

The naive `|current - target| > 15°F → out of control` rule was giving
pathological false-positives: a grill that just lit (current 71°F, target
410°F) or a grill that's cooling down after a cook would both get flagged
as "out of control" when they're doing exactly what the user asked for.

This classifier factors in TIME and INTENT:

  * ``ramping_up``    — engaged, target set, hasn't reached target yet,
                        elapsed time < expected ramp budget.
  * ``in_control``    — engaged, post-reach, gap within expected band.
  * ``out_of_control``— engaged, post-reach, gap exceeds expected band.
  * ``cooling_down``  — recently engaged, now disengaged or target=0,
                        temp above ambient.
  * ``manual_mode``   — engaged but no target set (user running fans/
                        heat open-loop — Venom still reports telemetry).
  * ``error``         — device reports non-zero error codes.
  * ``idle``          — disengaged, temp near ambient, no recent cook.

Phase 1 uses conservative heuristics for the ramp budget and
post-reach tolerance. Phase 2 swaps these for baseline-driven values
per target-temp band + firmware version (see
``cook_behavior_baselines``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TelemetryStreamEvent


# ── public classification states ────────────────────────────────────────

STATE_RAMPING_UP = "ramping_up"
STATE_IN_CONTROL = "in_control"
STATE_OUT_OF_CONTROL = "out_of_control"
STATE_COOLING_DOWN = "cooling_down"
STATE_MANUAL_MODE = "manual_mode"
STATE_ERROR = "error"
STATE_IDLE = "idle"
STATE_UNKNOWN = "unknown"

ALL_STATES = (
    STATE_RAMPING_UP,
    STATE_IN_CONTROL,
    STATE_OUT_OF_CONTROL,
    STATE_COOLING_DOWN,
    STATE_MANUAL_MODE,
    STATE_ERROR,
    STATE_IDLE,
    STATE_UNKNOWN,
)

STATE_LABELS: dict[str, str] = {
    STATE_RAMPING_UP: "Ramping up",
    STATE_IN_CONTROL: "In control",
    STATE_OUT_OF_CONTROL: "Out of control",
    STATE_COOLING_DOWN: "Cooling down",
    STATE_MANUAL_MODE: "Manual mode",
    STATE_ERROR: "Error",
    STATE_IDLE: "Idle",
    STATE_UNKNOWN: "Unknown",
}


# ── Phase 1 heuristic ramp budgets ──────────────────────────────────────
#
# Expected ramp time (seconds) from ~ambient to within REACH_THRESHOLD_F
# of target, as a function of target_temp. Based on conventional pellet/
# charcoal Venom behavior — ~8 min to 225°F, ~15 min to 400°F, ~22 min to
# 600°F. Phase 2 replaces this with learned percentile values per
# target-temp band and firmware_version.

REACH_THRESHOLD_F = 15.0           # within ±15°F of target = "reached"
RAMP_GRACE_SECONDS = 180           # 3-min grace after budget before flagging out-of-control
POST_REACH_TOLERANCE_F = 20.0      # Phase 1 post-reach gap allowed before "out of control"
COOLING_ENGAGED_WINDOW_S = 900     # within 15 min of last-engaged = still "cooling"
COOLING_MIN_TEMP_F = 150.0         # above this = still coasting hot
AMBIENT_CEILING_F = 120.0          # below this = idle (near ambient)
MIN_ENGAGED_SAMPLES_FOR_RAMP = 1   # need at least one prior engaged sample to measure ramp


def heuristic_ramp_budget_seconds(target_temp: float) -> int:
    """Phase 1 linear approximation. Replaced by baselines in Phase 2."""
    if target_temp <= 0:
        return 600
    # Floor 6 min, +1 min per 30°F over 200°F, cap 30 min.
    extra = max(0.0, target_temp - 200.0) / 30.0
    return int(min(1800, max(360, 360 + extra * 60)))


# ── data shapes ─────────────────────────────────────────────────────────

@dataclass
class CookStateResult:
    state: str
    confidence: float           # 0..1 — how sure we are
    reason: str                 # short human-readable
    target_temp: Optional[float]
    current_temp: Optional[float]
    gap_f: Optional[float]
    intensity: Optional[float]
    engaged: Optional[bool]
    door_open: Optional[bool]
    paused: Optional[bool]
    error_count: int
    ramp_elapsed_seconds: Optional[int]
    ramp_budget_seconds: Optional[int]
    expected_gap_f: Optional[float]   # gap tolerance we're comparing against
    is_anomalous: bool                # only true for out_of_control/error states
    sample_timestamp: Optional[datetime]
    classified_at: datetime


def _extract(raw_payload: dict | None) -> dict[str, Any]:
    if not isinstance(raw_payload, dict):
        return {}
    reported = ((raw_payload.get("device_data") or {}).get("reported")) or {}
    heat = (reported.get("heat") or {}).get("t2") or {}
    main_temp = reported.get("mainTemp")
    target = heat.get("trgt")
    gap = None
    if isinstance(main_temp, (int, float)) and isinstance(target, (int, float)):
        gap = float(main_temp) - float(target)
    errors = reported.get("errors") or []
    err_count = sum(1 for e in errors if e and (not isinstance(e, (int, float)) or int(e) != 0))
    return {
        "target_temp": target if isinstance(target, (int, float)) else None,
        "current_temp": main_temp if isinstance(main_temp, (int, float)) else None,
        "gap_f": gap,
        "intensity": heat.get("intensity"),
        "engaged": reported.get("engaged"),
        "paused": reported.get("paused"),
        "door_open": reported.get("doorOpn"),
        "error_count": err_count,
    }


def _engagement_onset(events: list[TelemetryStreamEvent]) -> Optional[datetime]:
    """Find the most recent rising-edge (not-engaged → engaged) in the
    ordered event list ending at ``events[-1]``. Returns the sample
    timestamp at which the current engagement window began.

    If the entire window shows engaged=true, returns the first event's
    timestamp (best available lower bound).
    """
    onset: Optional[datetime] = None
    for ev in events:
        sig = _extract(ev.raw_payload)
        if sig.get("engaged"):
            if onset is None:
                onset = ev.sample_timestamp
        else:
            onset = None
    return onset


def _last_engaged_timestamp(events: list[TelemetryStreamEvent]) -> Optional[datetime]:
    """Most recent timestamp where engaged was true. None if never engaged."""
    latest: Optional[datetime] = None
    for ev in events:
        sig = _extract(ev.raw_payload)
        if sig.get("engaged") and ev.sample_timestamp:
            if latest is None or ev.sample_timestamp > latest:
                latest = ev.sample_timestamp
    return latest


def classify_from_events(
    events: list[TelemetryStreamEvent],
    *,
    baseline_lookup: Optional[callable] = None,
    now: Optional[datetime] = None,
) -> CookStateResult:
    """Classify based on an ordered list of a single device's recent events.

    ``events`` must be sorted ascending by sample_timestamp. The LAST
    element is treated as "now"; earlier elements are used to measure
    engagement onset and trend. If the list has only one element, we
    classify using only that event — less accurate (can't measure ramp
    elapsed), but still meaningful.

    ``baseline_lookup`` — optional callable ``(target_temp, firmware_version)
    -> {ramp_budget_seconds, post_reach_tolerance_f}``. When None, the
    heuristic budget is used (Phase 1 default).
    """
    now = now or datetime.now(timezone.utc)
    if not events:
        return CookStateResult(
            state=STATE_UNKNOWN,
            confidence=0.0,
            reason="no recent events",
            target_temp=None, current_temp=None, gap_f=None, intensity=None,
            engaged=None, door_open=None, paused=None, error_count=0,
            ramp_elapsed_seconds=None, ramp_budget_seconds=None,
            expected_gap_f=None, is_anomalous=False,
            sample_timestamp=None, classified_at=now,
        )

    latest = events[-1]
    sig = _extract(latest.raw_payload)
    sample_ts = latest.sample_timestamp
    target = sig.get("target_temp")
    current = sig.get("current_temp")
    gap = sig.get("gap_f")
    intensity = sig.get("intensity")
    engaged = bool(sig.get("engaged"))
    paused = sig.get("paused")
    door = sig.get("door_open")
    errs = int(sig.get("error_count") or 0)

    # Firmware version for baseline lookup
    firmware = latest.firmware_version

    # ── ERROR supersedes everything ──
    if errs > 0:
        return CookStateResult(
            state=STATE_ERROR,
            confidence=1.0,
            reason=f"{errs} active error code(s)",
            target_temp=target, current_temp=current, gap_f=gap, intensity=intensity,
            engaged=engaged, door_open=door, paused=paused, error_count=errs,
            ramp_elapsed_seconds=None, ramp_budget_seconds=None,
            expected_gap_f=None, is_anomalous=True,
            sample_timestamp=sample_ts, classified_at=now,
        )

    # ── NOT ENGAGED branch ──
    if not engaged:
        last_eng = _last_engaged_timestamp(events[:-1])
        if last_eng and sample_ts:
            since_eng = (sample_ts - last_eng).total_seconds()
        else:
            since_eng = None

        # Still hot + recently engaged → cooling down
        if current is not None and current >= COOLING_MIN_TEMP_F and (
            (since_eng is not None and since_eng <= COOLING_ENGAGED_WINDOW_S)
            or since_eng is None and current >= 200.0
        ):
            return CookStateResult(
                state=STATE_COOLING_DOWN,
                confidence=0.8,
                reason=f"disengaged, {current:.0f}°F cooling",
                target_temp=target, current_temp=current, gap_f=gap, intensity=intensity,
                engaged=False, door_open=door, paused=paused, error_count=0,
                ramp_elapsed_seconds=None, ramp_budget_seconds=None,
                expected_gap_f=None, is_anomalous=False,
                sample_timestamp=sample_ts, classified_at=now,
            )
        # Cold + disengaged → idle
        return CookStateResult(
            state=STATE_IDLE,
            confidence=0.9,
            reason="disengaged, at ambient",
            target_temp=target, current_temp=current, gap_f=gap, intensity=intensity,
            engaged=False, door_open=door, paused=paused, error_count=0,
            ramp_elapsed_seconds=None, ramp_budget_seconds=None,
            expected_gap_f=None, is_anomalous=False,
            sample_timestamp=sample_ts, classified_at=now,
        )

    # ── ENGAGED branch ──

    # Manual mode: engaged with no/zero target — user running open-loop.
    if target is None or target <= 0:
        return CookStateResult(
            state=STATE_MANUAL_MODE,
            confidence=0.9,
            reason="engaged without temp target",
            target_temp=target, current_temp=current, gap_f=None, intensity=intensity,
            engaged=True, door_open=door, paused=paused, error_count=0,
            ramp_elapsed_seconds=None, ramp_budget_seconds=None,
            expected_gap_f=None, is_anomalous=False,
            sample_timestamp=sample_ts, classified_at=now,
        )

    # Engaged with a real target. Is the current sample reached yet?
    if current is None or gap is None:
        return CookStateResult(
            state=STATE_UNKNOWN,
            confidence=0.2,
            reason="engaged but no current temp reading",
            target_temp=target, current_temp=current, gap_f=gap, intensity=intensity,
            engaged=True, door_open=door, paused=paused, error_count=0,
            ramp_elapsed_seconds=None, ramp_budget_seconds=None,
            expected_gap_f=None, is_anomalous=False,
            sample_timestamp=sample_ts, classified_at=now,
        )

    # Baseline-driven (Phase 2) or heuristic (Phase 1) budget + tolerance.
    baseline = None
    if baseline_lookup is not None:
        try:
            baseline = baseline_lookup(target, firmware)
        except Exception:
            baseline = None
    ramp_budget = int(baseline.get("ramp_budget_seconds")) if baseline and baseline.get("ramp_budget_seconds") else heuristic_ramp_budget_seconds(target)
    tolerance = float(baseline.get("post_reach_tolerance_f")) if baseline and baseline.get("post_reach_tolerance_f") else POST_REACH_TOLERANCE_F

    # Engagement onset — may be None if we can't see the rising edge.
    onset = _engagement_onset(events)
    ramp_elapsed: Optional[int] = None
    if onset and sample_ts:
        ramp_elapsed = int((sample_ts - onset).total_seconds())

    reached = abs(gap) <= REACH_THRESHOLD_F
    within_ramp_budget = ramp_elapsed is None or ramp_elapsed <= ramp_budget + RAMP_GRACE_SECONDS

    # Ramping up: not yet reached AND (still within budget OR we can't
    # measure elapsed because onset is hidden beyond our window).
    if not reached and gap < 0 and within_ramp_budget:
        return CookStateResult(
            state=STATE_RAMPING_UP,
            confidence=0.85 if ramp_elapsed is not None else 0.6,
            reason=(
                f"ramping, {ramp_elapsed}s elapsed, budget {ramp_budget}s"
                if ramp_elapsed is not None
                else f"ramping (onset outside window), gap {gap:.0f}°F"
            ),
            target_temp=target, current_temp=current, gap_f=gap, intensity=intensity,
            engaged=True, door_open=door, paused=paused, error_count=0,
            ramp_elapsed_seconds=ramp_elapsed, ramp_budget_seconds=ramp_budget,
            expected_gap_f=None, is_anomalous=False,
            sample_timestamp=sample_ts, classified_at=now,
        )

    # Reached (or overshot) — evaluate post-reach tolerance.
    if abs(gap) <= tolerance:
        return CookStateResult(
            state=STATE_IN_CONTROL,
            confidence=0.9,
            reason=f"post-reach, gap {gap:+.0f}°F within ±{tolerance:.0f}",
            target_temp=target, current_temp=current, gap_f=gap, intensity=intensity,
            engaged=True, door_open=door, paused=paused, error_count=0,
            ramp_elapsed_seconds=ramp_elapsed, ramp_budget_seconds=ramp_budget,
            expected_gap_f=tolerance, is_anomalous=False,
            sample_timestamp=sample_ts, classified_at=now,
        )

    # Gap exceeds tolerance AND we're past the ramp budget → real anomaly.
    return CookStateResult(
        state=STATE_OUT_OF_CONTROL,
        confidence=0.85,
        reason=(
            f"gap {gap:+.0f}°F exceeds ±{tolerance:.0f}"
            + (f", {ramp_elapsed}s past onset (budget {ramp_budget}s)" if ramp_elapsed is not None else "")
        ),
        target_temp=target, current_temp=current, gap_f=gap, intensity=intensity,
        engaged=True, door_open=door, paused=paused, error_count=0,
        ramp_elapsed_seconds=ramp_elapsed, ramp_budget_seconds=ramp_budget,
        expected_gap_f=tolerance, is_anomalous=True,
        sample_timestamp=sample_ts, classified_at=now,
    )


# ── batch / fleet helpers ───────────────────────────────────────────────

def classify_fleet(
    db: Session,
    *,
    window_seconds: int = 900,
    baseline_lookup: Optional[callable] = None,
    now: Optional[datetime] = None,
) -> list[CookStateResult]:
    """Classify every device that has reported inside the window.

    Pulls up to ``window_seconds`` of events per device so we can measure
    engagement onset and ramp progress. We intentionally don't use a
    shorter window — Phase 1's heuristic ramp budget is up to ~30 min, so
    we need enough history to tell "just lit" from "stalled for 10 min".
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=window_seconds)

    events = db.execute(
        select(TelemetryStreamEvent)
        .where(TelemetryStreamEvent.sample_timestamp >= cutoff)
        .order_by(TelemetryStreamEvent.device_id, TelemetryStreamEvent.sample_timestamp)
    ).scalars().all()

    by_device: dict[str, list[TelemetryStreamEvent]] = {}
    for ev in events:
        by_device.setdefault(ev.device_id, []).append(ev)

    out: list[CookStateResult] = []
    for _, dev_events in by_device.items():
        out.append(classify_from_events(dev_events, baseline_lookup=baseline_lookup, now=now))
    return out


def result_to_dict(
    r: CookStateResult,
    *,
    mac: Optional[str] = None,
    device_id: Optional[str] = None,
    firmware_version: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "mac": mac,
        "device_id": device_id,
        "state": r.state,
        "state_label": STATE_LABELS.get(r.state, r.state),
        "confidence": round(r.confidence, 2),
        "reason": r.reason,
        "target_temp": r.target_temp,
        "current_temp": r.current_temp,
        "gap_f": r.gap_f,
        "intensity": r.intensity,
        "engaged": r.engaged,
        "door_open": r.door_open,
        "paused": r.paused,
        "error_count": r.error_count,
        "ramp_elapsed_seconds": r.ramp_elapsed_seconds,
        "ramp_budget_seconds": r.ramp_budget_seconds,
        "expected_gap_f": r.expected_gap_f,
        "is_anomalous": r.is_anomalous,
        "firmware_version": firmware_version,
        "sample_timestamp": r.sample_timestamp.isoformat() if r.sample_timestamp else None,
    }
