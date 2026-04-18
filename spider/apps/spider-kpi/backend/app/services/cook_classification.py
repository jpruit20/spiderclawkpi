"""Shared cook classification and session derivation for materialization.

This module provides a lightweight session-derivation pipeline that works
with plain ``EventRow`` objects (no SQLAlchemy ORM dependency) so it can be
used by both the nightly materializer and the S3 history import.

Two classification models live here, side by side:

* The *legacy* model (``classify_cook_style``, ``session_success``,
  ``stability_score``) — kept for back-compat with existing dashboard code
  and daily rollups that have historical values.

* The *intent + outcome* model added 2026-04-18 — separates what the user
  was trying to do (startup-assist, short cook, long cook) from how the
  device performed (reached-and-held, reached-not-held, did-not-reach,
  disconnect, error). This is the model the redesigned dashboard reads.

The new model also detects **lid-open disturbance events** from the
temperature curve and excludes those windows from stability scoring — so
``in_control_pct`` measures PID quality when the PID is actually in
control, not when the user has the dome open.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import median
from typing import Any, Iterable, Optional


# ── classification helpers ──

def classify_cook_style(duration_seconds: int, target_temp: float) -> str:
    if duration_seconds < 900:
        return "startup_only"
    if target_temp >= 400:
        return "hot_and_fast"
    if target_temp <= 275 and duration_seconds >= 1800:
        return "low_and_slow"
    if target_temp > 0:
        return "medium_heat"
    return "unclassified"


def classify_temp_range(target_temp: float) -> Optional[str]:
    if target_temp <= 0:
        return None
    if target_temp < 250:
        return "under_250"
    if target_temp <= 300:
        return "250_to_300"
    if target_temp <= 400:
        return "300_to_400"
    return "over_400"


def classify_duration_range(duration_seconds: int) -> str:
    if duration_seconds < 1800:
        return "under_30m"
    if duration_seconds < 7200:
        return "30m_to_2h"
    if duration_seconds < 14400:
        return "2h_to_4h"
    return "over_4h"


# ── lightweight event representation ──

@dataclass
class EventRow:
    """Protocol-compatible stand-in for TelemetryStreamEvent ORM objects."""
    device_id: str
    sample_timestamp: Any  # datetime or None
    created_at: Any  # datetime or None
    current_temp: Optional[float] = None
    target_temp: Optional[float] = None
    rssi: Optional[float] = None
    firmware_version: Optional[str] = None
    grill_type: Optional[str] = None
    engaged: bool = False
    error_codes_json: list = field(default_factory=list)
    raw_payload: dict = field(default_factory=dict)


# ── lightweight derived session ──

@dataclass
class LiteDerivedSession:
    """Simplified session — enough for cook classification, no event list."""
    device_id: str
    start_ts: Any
    end_ts: Any
    reached_target: bool
    stabilized: bool
    completed: bool
    disconnect_proxy: bool
    session_success: bool
    overshoot: bool
    stability_score: float
    target_temp: Optional[float]
    firmware_version: Optional[str]
    grill_type: Optional[str]
    error_count: int
    archetype: str


def _percentile(values: list[float], q: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 1)
    idx = (len(ordered) - 1) * q
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    fraction = idx - lo
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * fraction, 1)


# ── session derivation (same algorithm as telemetry_stream_summary._derive_sessions) ──

def derive_sessions_from_rows(
    device_id: str,
    events: list[EventRow],
    gap_minutes: int = 45,
) -> list[LiteDerivedSession]:
    """Group events by time gap and classify each group as a session."""
    if not events:
        return []
    ordered = sorted(events, key=lambda e: e.sample_timestamp or e.created_at)
    grouped: list[list[EventRow]] = []
    current: list[EventRow] = []
    previous_ts = None
    for event in ordered:
        ts = event.sample_timestamp or event.created_at
        if ts is None:
            continue
        if previous_ts and ts - previous_ts > timedelta(minutes=gap_minutes):
            if current:
                grouped.append(current)
            current = []
        current.append(event)
        previous_ts = ts
    if current:
        grouped.append(current)

    sessions: list[LiteDerivedSession] = []
    for group in grouped:
        first, last = group[0], group[-1]
        targets = [float(e.target_temp) for e in group if e.target_temp is not None and float(e.target_temp) > 0]
        target_temp = median(targets) if targets else None
        errors = sum(
            sum(1 for code in (e.error_codes_json or []) if int(code) != 0)
            for e in group
        )
        reached_target = False
        stabilize_ts = None
        overshoot = False
        stable_hits = 0
        post_target_deltas: list[float] = []
        temp_deltas: list[float] = []

        for item in group:
            ct = float(item.current_temp) if item.current_temp is not None else None
            if target_temp is not None and ct is not None:
                delta = ct - target_temp
                temp_deltas.append(abs(delta))
                if ct >= target_temp - 10:
                    reached_target = True
                if reached_target:
                    post_target_deltas.append(abs(delta))
                if ct > target_temp + 15:
                    overshoot = True
                if abs(delta) <= 15:
                    stable_hits += 1
                    if stable_hits >= 3 and stabilize_ts is None:
                        stabilize_ts = item.sample_timestamp or item.created_at
                else:
                    stable_hits = 0

        start_ts = first.sample_timestamp or first.created_at
        end_ts = last.sample_timestamp or last.created_at
        dur = int((end_ts - start_ts).total_seconds()) if start_ts and end_ts else 0
        disconnect_proxy = False
        if len(group) >= 2:
            max_gap = max(
                int(((group[i].sample_timestamp or group[i].created_at) - (group[i - 1].sample_timestamp or group[i - 1].created_at)).total_seconds())
                for i in range(1, len(group))
                if (group[i].sample_timestamp or group[i].created_at) and (group[i - 1].sample_timestamp or group[i - 1].created_at)
            )
            disconnect_proxy = max_gap > gap_minutes * 60
        stabilized = stabilize_ts is not None
        completed = reached_target and stabilized and bool(last.engaged is False or dur >= 1800)
        session_success = reached_target and stabilized and not disconnect_proxy and errors == 0
        scoring = post_target_deltas if post_target_deltas else temp_deltas
        stability_score = max(0.0, min(1.0, 1 - (_percentile(scoring, 0.5) or 0) / 50)) if scoring and target_temp else (1.0 if reached_target else 0.0)

        if disconnect_proxy:
            archetype = 'dropout'
        elif overshoot and not stabilized:
            archetype = 'overshoot'
        elif reached_target and not stabilized:
            archetype = 'oscillation'
        elif session_success:
            archetype = 'stable'
        else:
            archetype = 'incomplete'

        sessions.append(LiteDerivedSession(
            device_id=device_id,
            start_ts=start_ts,
            end_ts=end_ts,
            reached_target=reached_target,
            stabilized=stabilized,
            completed=completed,
            disconnect_proxy=disconnect_proxy,
            session_success=session_success,
            overshoot=overshoot,
            stability_score=round(stability_score, 3),
            target_temp=target_temp,
            firmware_version=last.firmware_version,
            grill_type=last.grill_type,
            error_count=errors,
            archetype=archetype,
        ))
    return sessions


# ── daily aggregation ──

def build_daily_cook_columns(sessions: list[LiteDerivedSession], device_ids: set[str] | None = None) -> dict[str, Any]:
    """Aggregate sessions into the 7 columns for telemetry_history_daily."""
    cook_styles: dict[str, int] = {"startup_only": 0, "hot_and_fast": 0, "low_and_slow": 0, "medium_heat": 0, "unclassified": 0}
    temp_ranges: dict[str, int] = {"under_250": 0, "250_to_300": 0, "300_to_400": 0, "over_400": 0}
    duration_ranges: dict[str, int] = {"under_30m": 0, "30m_to_2h": 0, "2h_to_4h": 0, "over_4h": 0}
    style_durations: dict[str, list[int]] = defaultdict(list)
    style_stability: dict[str, list[float]] = defaultdict(list)
    style_success: dict[str, list[bool]] = defaultdict(list)
    successful = 0

    for s in sessions:
        dur = int((s.end_ts - s.start_ts).total_seconds()) if s.start_ts and s.end_ts else 0
        temp = s.target_temp or 0

        style = classify_cook_style(dur, temp)
        cook_styles[style] += 1
        style_durations[style].append(dur)
        style_stability[style].append(s.stability_score)
        style_success[style].append(s.session_success)

        tr = classify_temp_range(temp)
        if tr:
            temp_ranges[tr] += 1
        duration_ranges[classify_duration_range(dur)] += 1
        if s.session_success:
            successful += 1

    total = len(sessions)
    style_details: dict[str, dict] = {}
    for name, count in cook_styles.items():
        if count == 0:
            continue
        durs = style_durations.get(name, [])
        stabs = style_stability.get(name, [])
        succs = style_success.get(name, [])
        style_details[name] = {
            "count": count,
            "pct": round(count / max(total, 1), 4),
            "avg_duration_seconds": round(sum(durs) / max(len(durs), 1)),
            "median_duration_seconds": round(median(durs)) if durs else 0,
            "avg_stability_score": round(sum(stabs) / max(len(stabs), 1), 3) if stabs else None,
            "success_rate": round(sum(1 for x in succs if x) / max(len(succs), 1), 4) if succs else None,
        }

    return {
        "session_count": total,
        "successful_sessions": successful,
        "cook_styles_json": cook_styles,
        "cook_style_details_json": style_details,
        "temp_range_json": temp_ranges,
        "duration_range_json": duration_ranges,
        "unique_devices_seen": len(device_ids) if device_ids is not None else None,
    }


# ═══════════════════════════════════════════════════════════════════════
# INTENT + OUTCOME MODEL (2026-04-18 redesign)
# ═══════════════════════════════════════════════════════════════════════
#
# Three upgrades over the legacy model:
#
#   1. **Intent ≠ outcome.** A 12-minute startup-assist cook that hit
#      target in 4 minutes is a *success at its intent* — user wanted a
#      quick fire-up. Rolling it into `cook_success_rate` as a failure
#      made the top-line meaningless.
#
#   2. **Disturbance detection.** When the user opens the grill dome the
#      pit-probe reads a sharp temperature drop. The Venom firmware
#      detects this, shuts the fan off (to not over-stoke coals), and
#      resumes PID after recovery. That's correct operation — but naive
#      stability scoring sees 50°F deviations and flags the device as
#      unstable. We now segment sessions into disturbance windows vs
#      in-control windows and only score the latter.
#
#   3. **Held-target rate** replaces cook_success_rate as the headline
#      PID metric. Numerator = sessions that reached target and held
#      within ±15°F for ≥80% of the in-control time. Denominator
#      *excludes* startup-assist and disconnect sessions.

# ── intent bands ────────────────────────────────────────────────────────

INTENT_STARTUP_MAX_SECONDS = 15 * 60          # ≤ 15 min = startup assist
INTENT_SHORT_MAX_SECONDS = 60 * 60            # 15-60 min = short cook
INTENT_MEDIUM_MAX_SECONDS = 180 * 60          # 60-180 min = medium cook
                                              # > 180 min = long cook


def classify_cook_intent(duration_seconds: int, target_temp: Optional[float]) -> str:
    """What was the user trying to do?

    Orthogonal to outcome — a startup_assist can still 'succeed' at its
    intent (reached target quickly) or 'fail' (user disengaged before
    the fire was established).
    """
    if target_temp is None or target_temp <= 0:
        # No target set — can't classify intent meaningfully.
        return "unclassified"
    if duration_seconds <= INTENT_STARTUP_MAX_SECONDS:
        return "startup_assist"
    if duration_seconds <= INTENT_SHORT_MAX_SECONDS:
        return "short_cook"
    if duration_seconds <= INTENT_MEDIUM_MAX_SECONDS:
        return "medium_cook"
    return "long_cook"


INTENT_LABELS: dict[str, str] = {
    "startup_assist": "Startup assist (≤15m)",
    "short_cook": "Short cook (15-60m)",
    "medium_cook": "Medium cook (1-3h)",
    "long_cook": "Long cook (3h+)",
    "unclassified": "Unclassified",
}


# ── disturbance detection ──────────────────────────────────────────────

# A disturbance is a rapid temperature drop from near-target, typically
# caused by the user opening the grill dome. These are excluded from
# in-control stability scoring.

# Tunables — conservative defaults chosen so we only flag clear
# disturbances; small PID wobbles won't trigger. Tune per firmware later.
DISTURBANCE_DROP_THRESHOLD_F = 30.0            # ≥30°F drop counts
DISTURBANCE_WINDOW_SAMPLES = 3                 # over this many consecutive samples (~1-2 min)
DISTURBANCE_PRE_NEAR_TARGET_F = 25.0           # pre-drop temp within ±25°F of target
DISTURBANCE_RECOVERY_F = 15.0                  # event ends when temp is back within ±15°F


@dataclass
class DisturbanceEvent:
    start_ts: datetime
    end_ts: Optional[datetime]          # None if the session ended before recovery
    start_temp: float
    min_temp: float
    recovered: bool
    recovery_seconds: Optional[int]


@dataclass
class TempPoint:
    ts: datetime
    temp: float


def _parse_iso(s: Any) -> Optional[datetime]:
    """Parse an ISO-format timestamp string — handles both +00:00 and
    Z-suffixed; returns None on failure."""
    if s is None:
        return None
    if isinstance(s, datetime):
        return s
    try:
        if isinstance(s, str):
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            return datetime.fromisoformat(s)
    except Exception:
        return None
    return None


def detect_disturbances(
    temp_series: list[TempPoint],
    target_temp: float,
) -> list[DisturbanceEvent]:
    """Identify disturbance (lid-open) windows in the temp curve.

    Heuristic:
      * Starting state is "near target" — temp within ±25°F of target.
      * A disturbance STARTS when the temp drops by ≥30°F over the next
        ``DISTURBANCE_WINDOW_SAMPLES`` samples.
      * A disturbance ENDS when temp returns to within ±15°F of target.
      * If the session ends while still in disturbance, the event is
        unrecovered.
    """
    if not temp_series or target_temp <= 0:
        return []

    events: list[DisturbanceEvent] = []
    i = 0
    n = len(temp_series)
    while i < n:
        pt = temp_series[i]
        if pt.temp is None:
            i += 1
            continue
        # Only start looking if current temp is near target.
        if abs(pt.temp - target_temp) > DISTURBANCE_PRE_NEAR_TARGET_F:
            i += 1
            continue
        # Look ahead: is there a big drop in the next window?
        window_end = min(i + DISTURBANCE_WINDOW_SAMPLES, n)
        drop_found_at = None
        for j in range(i + 1, window_end):
            if temp_series[j].temp is not None and (pt.temp - temp_series[j].temp) >= DISTURBANCE_DROP_THRESHOLD_F:
                drop_found_at = j
                break
        if drop_found_at is None:
            i += 1
            continue
        # We have a disturbance. Find the minimum within the next ~5 min.
        disturb_start = pt
        min_pt = temp_series[drop_found_at]
        look_end = n
        # Cap the min-search to a reasonable window (~5 min of samples).
        for k in range(drop_found_at + 1, min(drop_found_at + 10, n)):
            if temp_series[k].temp is not None and temp_series[k].temp < min_pt.temp:
                min_pt = temp_series[k]
        # Find recovery.
        recovery_idx = None
        for k in range(drop_found_at, look_end):
            if temp_series[k].temp is not None and abs(temp_series[k].temp - target_temp) <= DISTURBANCE_RECOVERY_F:
                recovery_idx = k
                break
        if recovery_idx is not None:
            end_ts = temp_series[recovery_idx].ts
            recovery_seconds = int((end_ts - disturb_start.ts).total_seconds()) if disturb_start.ts and end_ts else None
            events.append(DisturbanceEvent(
                start_ts=disturb_start.ts,
                end_ts=end_ts,
                start_temp=disturb_start.temp,
                min_temp=min_pt.temp,
                recovered=True,
                recovery_seconds=recovery_seconds,
            ))
            i = recovery_idx + 1
        else:
            events.append(DisturbanceEvent(
                start_ts=disturb_start.ts,
                end_ts=None,
                start_temp=disturb_start.temp,
                min_temp=min_pt.temp,
                recovered=False,
                recovery_seconds=None,
            ))
            break
    return events


# ── PID quality (in-control %) ──────────────────────────────────────────

@dataclass
class PidQuality:
    """Result of scoring a session's post-reach temperature behavior
    excluding disturbance windows."""
    in_control_pct: Optional[float]           # None if no post-reach samples
    in_control_samples: int
    post_reach_samples: int
    max_overshoot_f: Optional[float]          # positive-side deviation (target-relative)
    max_undershoot_f: Optional[float]         # negative-side (excluding disturbances)
    avg_recovery_seconds: Optional[int]
    disturbance_count: int
    total_disturbance_seconds: int


def compute_pid_quality(
    temp_series: list[TempPoint],
    target_temp: float,
    disturbances: list[DisturbanceEvent],
    in_control_tolerance_f: float = 15.0,
) -> PidQuality:
    """Score PID performance over post-reach, non-disturbance samples.

    "Post-reach" = samples occurring after the first time current_temp
    ≥ target_temp - 10°F. Before that, the device is still ramping up
    to temperature, which is a different phase of operation.

    "In-control" = within ±``in_control_tolerance_f`` of target_temp.

    Disturbance windows are excluded from both numerator and denominator,
    so a user who opens the lid 5 times during a cook doesn't drag the
    device's PID score down.
    """
    if not temp_series or target_temp <= 0:
        return PidQuality(None, 0, 0, None, None, None, 0, 0)

    # Find first-reach point.
    reach_idx = None
    for i, pt in enumerate(temp_series):
        if pt.temp is not None and pt.temp >= target_temp - 10:
            reach_idx = i
            break
    if reach_idx is None:
        return PidQuality(
            None, 0, 0, None, None, None,
            disturbance_count=len(disturbances),
            total_disturbance_seconds=sum(
                int((d.end_ts - d.start_ts).total_seconds()) if d.end_ts and d.start_ts else 0
                for d in disturbances
            ),
        )

    # Build a set of (start_ts, end_ts) tuples for disturbance exclusion.
    disturb_windows: list[tuple[datetime, Optional[datetime]]] = [
        (d.start_ts, d.end_ts) for d in disturbances
    ]

    def _in_disturbance(ts: datetime) -> bool:
        for (ds, de) in disturb_windows:
            if ds is None:
                continue
            if de is None and ts >= ds:
                return True
            if de is not None and ds <= ts <= de:
                return True
        return False

    post_reach = temp_series[reach_idx:]
    in_control = 0
    total_scored = 0
    deltas_for_overshoot: list[float] = []
    deltas_for_undershoot: list[float] = []

    for pt in post_reach:
        if pt.temp is None or pt.ts is None:
            continue
        if _in_disturbance(pt.ts):
            continue
        total_scored += 1
        delta = pt.temp - target_temp
        if abs(delta) <= in_control_tolerance_f:
            in_control += 1
        if delta > 0:
            deltas_for_overshoot.append(delta)
        elif delta < 0:
            deltas_for_undershoot.append(-delta)

    in_control_pct = (in_control / total_scored) if total_scored > 0 else None
    max_overshoot = max(deltas_for_overshoot) if deltas_for_overshoot else None
    max_undershoot = max(deltas_for_undershoot) if deltas_for_undershoot else None

    recovered = [d.recovery_seconds for d in disturbances if d.recovered and d.recovery_seconds is not None]
    avg_recovery = int(sum(recovered) / len(recovered)) if recovered else None

    total_dist_sec = sum(
        int((d.end_ts - d.start_ts).total_seconds()) if d.end_ts and d.start_ts else 0
        for d in disturbances
    )

    return PidQuality(
        in_control_pct=round(in_control_pct, 4) if in_control_pct is not None else None,
        in_control_samples=in_control,
        post_reach_samples=total_scored,
        max_overshoot_f=round(max_overshoot, 1) if max_overshoot is not None else None,
        max_undershoot_f=round(max_undershoot, 1) if max_undershoot is not None else None,
        avg_recovery_seconds=avg_recovery,
        disturbance_count=len(disturbances),
        total_disturbance_seconds=total_dist_sec,
    )


# ── outcome classification ──────────────────────────────────────────────

# Success bar: to be "reached_and_held" we require in-control-pct ≥ this
# over the post-reach non-disturbance window AND a reasonable post-reach
# sample size. Short sessions get a softer bar.
HELD_THRESHOLD_LONG_COOK = 0.80           # long cooks: 80% in-control
HELD_THRESHOLD_SHORT_COOK = 0.70          # short/medium: 70% (less time to stabilize)
HELD_THRESHOLD_STARTUP = 1.00             # startup: just reaching target in time is success
MIN_POST_REACH_SAMPLES_FOR_HELD = 6       # below this, call it "reached_not_held" (not enough data)


def classify_cook_outcome(
    intent: str,
    reached_target: bool,
    disconnect: bool,
    error_count: int,
    pid: PidQuality,
) -> str:
    """Determine how the cook turned out.

    Outcomes:
      * ``reached_and_held``  — target reached; PID held it within tolerance
                                for the expected threshold.
      * ``reached_not_held``  — reached target but couldn't sustain.
      * ``did_not_reach``     — never reached target (user pulled off, short
                                cook, hardware issue, bad start, etc.).
      * ``disconnect``        — lost signal mid-cook; outcome unknowable.
      * ``error``             — device reported error codes.
    """
    if error_count > 0:
        return "error"
    if disconnect:
        return "disconnect"
    if not reached_target:
        return "did_not_reach"

    # Reached. Was it held?
    if pid.in_control_pct is None or pid.post_reach_samples < MIN_POST_REACH_SAMPLES_FOR_HELD:
        # For startup_assist, just reaching target counts.
        if intent == "startup_assist":
            return "reached_and_held"
        return "reached_not_held"

    if intent == "startup_assist":
        # Startup assist already hit target; that's a success at its intent.
        return "reached_and_held"
    threshold = (
        HELD_THRESHOLD_LONG_COOK if intent == "long_cook"
        else HELD_THRESHOLD_SHORT_COOK
    )
    return "reached_and_held" if pid.in_control_pct >= threshold else "reached_not_held"


OUTCOME_LABELS: dict[str, str] = {
    "reached_and_held": "Reached & held",
    "reached_not_held": "Reached but not held",
    "did_not_reach": "Did not reach target",
    "disconnect": "Disconnected",
    "error": "Device error",
}

# Outcomes that count toward the "held-target rate" denominator.
# Startup-assist and disconnect are EXCLUDED — they aren't representative
# of PID-holding performance.
TARGET_SEEKING_OUTCOMES = {"reached_and_held", "reached_not_held", "did_not_reach"}


def is_held_target(outcome: str) -> bool:
    return outcome == "reached_and_held"


def counts_toward_held_rate(intent: str, outcome: str) -> bool:
    """Held-target rate denominator: non-startup, non-disconnect, non-error."""
    if intent == "startup_assist":
        return False
    if outcome in ("disconnect", "error"):
        return False
    return outcome in TARGET_SEEKING_OUTCOMES


# ── end-to-end scoring from a temp-series JSON blob ─────────────────────

def score_session_from_temp_series(
    temp_series_json: list[dict],
    target_temp: Optional[float],
    duration_seconds: int,
    disconnect_proxy: bool,
    error_count: int,
    reached_target: bool,
) -> dict[str, Any]:
    """Top-level helper: given a stored session's ``actual_temp_time_series``
    JSON (list of {t: iso, c: temp}) plus a few session-level fields,
    compute the full new-model metrics in one shot.

    Safe to call on existing telemetry_sessions rows — used by the
    re-derivation script.
    """
    points: list[TempPoint] = []
    for p in (temp_series_json or []):
        if not isinstance(p, dict):
            continue
        ts = _parse_iso(p.get("t"))
        temp = p.get("c")
        if ts is None or temp is None:
            continue
        try:
            temp_f = float(temp)
        except (TypeError, ValueError):
            continue
        points.append(TempPoint(ts=ts, temp=temp_f))

    intent = classify_cook_intent(duration_seconds, target_temp)
    if target_temp is None or target_temp <= 0 or not points:
        # Can't do PID analysis without target or curve. Return minimal info.
        return {
            "cook_intent": intent,
            "cook_outcome": "disconnect" if disconnect_proxy else ("error" if error_count > 0 else ("did_not_reach" if not reached_target else "reached_not_held")),
            "held_target": False,
            "disturbance_count": 0,
            "total_disturbance_seconds": 0,
            "avg_recovery_seconds": None,
            "in_control_pct": None,
            "max_overshoot_f": None,
            "max_undershoot_f": None,
            "post_reach_samples": 0,
        }

    disturbances = detect_disturbances(points, float(target_temp))
    pid = compute_pid_quality(points, float(target_temp), disturbances)
    outcome = classify_cook_outcome(
        intent=intent,
        reached_target=reached_target,
        disconnect=disconnect_proxy,
        error_count=error_count,
        pid=pid,
    )
    return {
        "cook_intent": intent,
        "cook_outcome": outcome,
        "held_target": is_held_target(outcome),
        "disturbance_count": pid.disturbance_count,
        "total_disturbance_seconds": pid.total_disturbance_seconds,
        "avg_recovery_seconds": pid.avg_recovery_seconds,
        "in_control_pct": pid.in_control_pct,
        "max_overshoot_f": pid.max_overshoot_f,
        "max_undershoot_f": pid.max_undershoot_f,
        "post_reach_samples": pid.post_reach_samples,
    }


# ── richer daily aggregation ────────────────────────────────────────────

def build_daily_quality_columns(
    session_scores: list[dict[str, Any]],
) -> dict[str, Any]:
    """Roll a day's worth of scored sessions into the new aggregate columns.

    Inputs:
      * ``session_scores`` — list of dicts returned by
        ``score_session_from_temp_series``.

    Output is a dict suitable for upserting into telemetry_history_daily's
    new columns.
    """
    intent_counts: dict[str, int] = defaultdict(int)
    outcome_counts: dict[str, int] = defaultdict(int)
    held_target = 0
    target_seeking = 0
    in_control_values: list[float] = []
    disturbances: list[int] = []
    recovery_seconds: list[int] = []
    overshoots: list[float] = []

    for s in session_scores:
        intent = s.get("cook_intent") or "unclassified"
        outcome = s.get("cook_outcome") or "unknown"
        intent_counts[intent] += 1
        outcome_counts[outcome] += 1
        if counts_toward_held_rate(intent, outcome):
            target_seeking += 1
            if s.get("held_target"):
                held_target += 1
        if s.get("in_control_pct") is not None:
            in_control_values.append(float(s["in_control_pct"]))
        disturbances.append(int(s.get("disturbance_count") or 0))
        if s.get("avg_recovery_seconds") is not None:
            recovery_seconds.append(int(s["avg_recovery_seconds"]))
        if s.get("max_overshoot_f") is not None:
            overshoots.append(float(s["max_overshoot_f"]))

    held_target_rate = (held_target / target_seeking) if target_seeking > 0 else None
    avg_in_control = (sum(in_control_values) / len(in_control_values)) if in_control_values else None
    avg_disturbances = (sum(disturbances) / len(disturbances)) if disturbances else None
    avg_recovery = (sum(recovery_seconds) / len(recovery_seconds)) if recovery_seconds else None
    avg_overshoot = (sum(overshoots) / len(overshoots)) if overshoots else None

    return {
        "cook_intents_json": dict(intent_counts),
        "cook_outcomes_json": dict(outcome_counts),
        "held_target_sessions": held_target,
        "target_seeking_sessions": target_seeking,
        "held_target_rate": round(held_target_rate, 4) if held_target_rate is not None else None,
        "avg_in_control_pct": round(avg_in_control, 4) if avg_in_control is not None else None,
        "avg_disturbances_per_cook": round(avg_disturbances, 2) if avg_disturbances is not None else None,
        "avg_recovery_seconds": round(avg_recovery, 1) if avg_recovery is not None else None,
        "avg_overshoot_f": round(avg_overshoot, 1) if avg_overshoot is not None else None,
    }
