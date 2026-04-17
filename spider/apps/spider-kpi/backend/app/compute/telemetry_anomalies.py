"""Anomaly detection on daily fleet telemetry.

Uses a trailing-14-day baseline and a **modified z-score** (median + MAD)
rather than mean/stdev. Fleet telemetry is heavy-tailed — weekend peaks,
holiday spikes, firmware rollouts, partial days — so mean/stdev flags
too many false positives. The modified z-score (Iglewicz & Hoaglin, 1993)
is robust to outliers in the baseline window itself.

Metrics tracked:

  * ``cook_success_rate``   — daily successful_sessions / session_count.
    Low-n days (< 50 sessions) are excluded from baseline AND from
    scoring, matching dashboard behavior.
  * ``error_rate``          — daily error_events / total_events.
  * ``active_devices``      — daily unique devices reporting shadow state.
  * ``avg_rssi``            — daily mean RSSI (signal strength).
  * ``avg_cook_temp``       — daily mean requested cook temperature.

Partial days (today in ET) are always excluded — mid-day rollups don't
represent a full day's data.

The scoring thresholds below are intentionally conservative for the
initial launch; they're tuned based on what we expect "normal" to look
like in aggregate. Once the v2 S3 backfill finishes and we have clean
2+ years of session-level data, these will be re-tuned against the
real distribution per-metric.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import TelemetryAnomaly, TelemetryHistoryDaily


logger = logging.getLogger(__name__)
BUSINESS_TZ = ZoneInfo("America/New_York")

# Severity thresholds on |modified_z_score|. Starting conservative —
# will re-tune once the full 2-year backfill has finished and we see
# the real distribution per metric. Iglewicz & Hoaglin recommend 3.5
# as the general "potential outlier" cutoff.
SEVERITY_WARN = 3.5
SEVERITY_CRITICAL = 5.0

LOW_N_SESSION_FLOOR = 50          # mirrors dashboard suppression
BASELINE_WINDOW_DAYS = 14
MIN_BASELINE_SAMPLES = 7          # need ≥7 non-partial days of baseline data


Direction = Literal["high", "low"]
Severity = Literal["info", "warn", "critical"]


def _modified_z(value: float, med: float, mad: float) -> float:
    """Iglewicz-Hoaglin modified z-score. MAD-of-0 falls back to 0 so we
    don't false-positive on perfectly flat baselines."""
    if mad <= 0:
        return 0.0
    return 0.6745 * (value - med) / mad


def _mad(values: list[float], med: float) -> float:
    return median([abs(v - med) for v in values]) if values else 0.0


def _severity_for(z: float) -> Optional[Severity]:
    az = abs(z)
    if az >= SEVERITY_CRITICAL:
        return "critical"
    if az >= SEVERITY_WARN:
        return "warn"
    return None  # below threshold — not an anomaly


def _direction_for(z: float) -> Direction:
    return "high" if z > 0 else "low"


def _daily_cook_success(row: TelemetryHistoryDaily) -> Optional[float]:
    n = row.session_count or 0
    if n < LOW_N_SESSION_FLOOR:
        return None
    return (row.successful_sessions or 0) / n


def _daily_error_rate(row: TelemetryHistoryDaily) -> Optional[float]:
    total = row.total_events or 0
    if total <= 0:
        return None
    return (row.error_events or 0) / total


METRICS = {
    "cook_success_rate": ("Cook success rate", _daily_cook_success, "fraction", "{:.1%}"),
    "error_rate":        ("Error rate",        _daily_error_rate,  "fraction", "{:.2%}"),
    "active_devices":    ("Active devices",    lambda r: float(r.active_devices or 0), "count", "{:.0f}"),
    "avg_rssi":          ("Avg RSSI",          lambda r: float(r.avg_rssi) if r.avg_rssi is not None else None, "dBm", "{:.1f}"),
    "avg_cook_temp":     ("Avg cook temp",     lambda r: float(r.avg_cook_temp) if r.avg_cook_temp is not None else None, "°F", "{:.0f}"),
}


def _is_partial_day(business_date: date) -> bool:
    today_et = datetime.now(BUSINESS_TZ).date()
    return business_date >= today_et


def detect_anomalies(
    db: Session,
    business_date: Optional[date] = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Score the given day (or the most recent non-partial day if None).

    Returns a dict with ``business_date``, the list of anomalies
    detected, and per-metric diagnostic info.
    """
    today_et = datetime.now(BUSINESS_TZ).date()
    if business_date is None:
        business_date = today_et - timedelta(days=1)  # yesterday = latest complete day

    if _is_partial_day(business_date):
        return {"ok": False, "reason": "partial_day_skip", "business_date": business_date.isoformat()}

    # Pull baseline rows: the 14 days BEFORE business_date (exclusive).
    baseline_start = business_date - timedelta(days=BASELINE_WINDOW_DAYS)
    rows = db.execute(
        select(TelemetryHistoryDaily)
        .where(
            TelemetryHistoryDaily.business_date >= baseline_start,
            TelemetryHistoryDaily.business_date <= business_date,
        )
        .order_by(TelemetryHistoryDaily.business_date)
    ).scalars().all()

    target_row = next((r for r in rows if r.business_date == business_date), None)
    if target_row is None:
        return {"ok": False, "reason": "no_row_for_date", "business_date": business_date.isoformat()}
    baseline_rows = [r for r in rows if r.business_date < business_date]

    results: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {}

    for metric, (label, extractor, unit, fmt) in METRICS.items():
        target_value = extractor(target_row)
        if target_value is None:
            diagnostics[metric] = {"skipped": "target_value_none"}
            continue

        baseline_values: list[float] = []
        for r in baseline_rows:
            v = extractor(r)
            if v is not None:
                baseline_values.append(float(v))
        if len(baseline_values) < MIN_BASELINE_SAMPLES:
            diagnostics[metric] = {"skipped": f"insufficient_baseline_n={len(baseline_values)}"}
            continue

        med = median(baseline_values)
        mad = _mad(baseline_values, med)
        z = _modified_z(target_value, med, mad)
        severity = _severity_for(z)
        diagnostics[metric] = {
            "value": target_value, "median": med, "mad": mad, "z": z,
            "severity": severity, "baseline_n": len(baseline_values),
        }
        if severity is None:
            continue

        direction = _direction_for(z)
        summary = (
            f"{label} for {business_date} is {fmt.format(target_value)}, "
            f"{'above' if direction == 'high' else 'below'} the 14-day median "
            f"{fmt.format(med)} (MAD={fmt.format(mad)}, modified z={z:+.2f}, n={len(baseline_values)})."
        )

        payload = {
            "business_date": business_date,
            "metric": metric,
            "value": float(target_value),
            "baseline_median": float(med),
            "baseline_mad": float(mad),
            "modified_z_score": float(z),
            "direction": direction,
            "severity": severity,
            "sample_size": len(baseline_values),
            "summary": summary,
            "status": "new",
        }
        results.append(payload)

        if persist:
            stmt = pg_insert(TelemetryAnomaly).values(**payload)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_telemetry_anomalies_date_metric",
                set_={k: stmt.excluded[k] for k in (
                    "value", "baseline_median", "baseline_mad", "modified_z_score",
                    "direction", "severity", "sample_size", "summary",
                )},
            )
            db.execute(stmt)
    if persist:
        db.commit()

    return {
        "ok": True,
        "business_date": business_date.isoformat(),
        "anomalies_found": len(results),
        "anomalies": results,
        "diagnostics": diagnostics,
        "baseline_window_days": BASELINE_WINDOW_DAYS,
    }


def backfill_anomalies(
    db: Session,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> dict[str, Any]:
    """Run detect_anomalies() across a date range. Useful for one-time
    historical scoring once the v2 S3 backfill completes."""
    today_et = datetime.now(BUSINESS_TZ).date()
    if end_date is None:
        end_date = today_et - timedelta(days=1)
    if start_date is None:
        start_date = end_date - timedelta(days=365)

    cur = start_date
    total_scored = 0
    total_anomalies = 0
    while cur <= end_date:
        r = detect_anomalies(db, business_date=cur, persist=True)
        if r.get("ok"):
            total_scored += 1
            total_anomalies += r.get("anomalies_found", 0)
        cur = cur + timedelta(days=1)
    return {
        "ok": True,
        "range_start": start_date.isoformat(),
        "range_end": end_date.isoformat(),
        "days_scored": total_scored,
        "total_anomalies": total_anomalies,
    }
