"""Shared cook classification and session derivation for materialization.

This module provides a lightweight session-derivation pipeline that works
with plain ``EventRow`` objects (no SQLAlchemy ORM dependency) so it can be
used by both the nightly materializer and the S3 history import.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from statistics import median
from typing import Any, Optional


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
