"""Trend deltas + rolling-baseline anomaly detection.

Two related concerns wrapped in one service:

1. **Trend deltas** — for any time-series metric, compute "current
   value vs 7d-prior" and "vs 28d-prior" with deterministic formatting
   for KPI tiles. The frontend renders the resulting arrow + % change.

2. **Anomaly detection** — flag when the current value is statistically
   off from its rolling 28-day mean. Surfaces in the Recommendations
   engine via dedicated generators so the dashboard tells you "cook
   success dropped 7pts this week vs 28d baseline" instead of just
   "cook success is 62%".

Both functions are pure: pass a series, get back a structured result.
The service does NOT decide which metrics to evaluate — that's per-page
configuration. This keeps the helper composable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from statistics import mean, pstdev
from typing import Any, Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass
class TrendDelta:
    """Result of comparing a current window to a prior window."""
    current: float
    prior: float
    delta_abs: float
    delta_pct: Optional[float]  # None when prior is 0 (avoid div/0 + ∞%)
    direction: str  # 'up' | 'down' | 'flat'

    def to_dict(self) -> dict[str, Any]:
        return {
            "current": round(self.current, 2),
            "prior": round(self.prior, 2),
            "delta_abs": round(self.delta_abs, 2),
            "delta_pct": round(self.delta_pct, 1) if self.delta_pct is not None else None,
            "direction": self.direction,
        }


def trend_delta(current: float, prior: float, *, flat_threshold_pct: float = 1.0) -> TrendDelta:
    """Two-sample delta for KPI tiles. ``flat_threshold_pct`` keeps the
    arrow off when the move is noise — anything <1% reports as flat."""
    delta_abs = current - prior
    delta_pct: Optional[float] = None
    if prior:
        delta_pct = (delta_abs / abs(prior)) * 100.0
    if delta_pct is None:
        direction = "up" if delta_abs > 0 else "down" if delta_abs < 0 else "flat"
    elif abs(delta_pct) < flat_threshold_pct:
        direction = "flat"
    else:
        direction = "up" if delta_pct > 0 else "down"
    return TrendDelta(current=current, prior=prior, delta_abs=delta_abs, delta_pct=delta_pct, direction=direction)


# ── Anomaly detection ───────────────────────────────────────────────


@dataclass
class AnomalyResult:
    """Result of comparing the current value to a rolling baseline."""
    current: float
    baseline_mean: float
    baseline_std: float
    z_score: float                # how many σ off the mean
    severity: str                  # 'normal' | 'mild' | 'moderate' | 'critical'
    direction: str                 # 'above' | 'below' | 'flat'
    n_observations: int            # sample size for the baseline

    def to_dict(self) -> dict[str, Any]:
        return {
            "current": round(self.current, 2),
            "baseline_mean": round(self.baseline_mean, 2),
            "baseline_std": round(self.baseline_std, 2),
            "z_score": round(self.z_score, 2),
            "severity": self.severity,
            "direction": self.direction,
            "n_observations": self.n_observations,
        }


def detect_anomaly(
    current: float,
    history: Iterable[float],
    *,
    min_observations: int = 7,
    mild_z: float = 1.5,
    moderate_z: float = 2.5,
    critical_z: float = 3.5,
) -> AnomalyResult:
    """Z-score-based anomaly detection over a rolling window.

    Severity tiers chosen so 'mild' is "worth noting" (~13% of normal
    daily samples), 'moderate' is "actively unusual" (~1%), 'critical'
    is "almost certainly a real signal" (<0.05%). Caller decides which
    tiers to surface — the recommendations engine usually filters on
    moderate+ to avoid noise.
    """
    samples = [float(h) for h in history if h is not None]
    if len(samples) < min_observations:
        return AnomalyResult(
            current=current, baseline_mean=0.0, baseline_std=0.0,
            z_score=0.0, severity="normal", direction="flat", n_observations=len(samples),
        )
    mu = mean(samples)
    sd = pstdev(samples) if len(samples) > 1 else 0.0
    if sd == 0:
        # Constant baseline — can't compute z. Compare to mean directly.
        return AnomalyResult(
            current=current, baseline_mean=mu, baseline_std=0.0,
            z_score=0.0,
            severity="normal" if current == mu else "mild",
            direction="above" if current > mu else "below" if current < mu else "flat",
            n_observations=len(samples),
        )
    z = (current - mu) / sd
    if abs(z) >= critical_z:
        severity = "critical"
    elif abs(z) >= moderate_z:
        severity = "moderate"
    elif abs(z) >= mild_z:
        severity = "mild"
    else:
        severity = "normal"
    direction = "above" if z > 0 else "below" if z < 0 else "flat"
    return AnomalyResult(
        current=current, baseline_mean=mu, baseline_std=sd,
        z_score=z, severity=severity, direction=direction,
        n_observations=len(samples),
    )


# ── Convenience: pull common metrics from KPIDaily / TelemetryHistoryDaily ──


def kpi_daily_series(db: Session, column: str, days: int = 35) -> list[float]:
    """Fetch a column from kpi_daily as a chronological list of floats.

    Whitelist of columns to avoid SQL injection (column comes from the
    caller — needs to be a real column name on KPIDaily)."""
    SAFE_COLS = {
        "revenue", "orders", "tickets_created", "tickets_resolved",
        "csat", "first_response_time", "resolution_time", "sla_breach_rate",
        "open_backlog", "reopen_rate", "tickets_per_100_orders",
        "average_order_value", "sessions", "conversion_rate",
        "ad_spend", "mer", "cost_per_purchase",
    }
    if column not in SAFE_COLS:
        raise ValueError(f"refusing to query unknown kpi column: {column!r}")
    rows = db.execute(text(f"""
        SELECT {column}::float AS v
        FROM kpi_daily
        WHERE business_date >= CURRENT_DATE - INTERVAL '{int(days)} days'
          AND business_date < CURRENT_DATE
          AND {column} IS NOT NULL
        ORDER BY business_date
    """)).all()
    return [float(r.v) for r in rows]


def cook_success_rate_series(db: Session, days: int = 35) -> list[float]:
    """Cook success rate is derived: successful_sessions / session_count.
    Skips days with zero sessions to avoid 0/0 dragging the mean."""
    rows = db.execute(text(f"""
        SELECT (successful_sessions::float / NULLIF(session_count, 0)) AS v
        FROM telemetry_history_daily
        WHERE business_date >= CURRENT_DATE - INTERVAL '{int(days)} days'
          AND business_date < CURRENT_DATE
          AND session_count IS NOT NULL
          AND session_count > 0
          AND successful_sessions IS NOT NULL
        ORDER BY business_date
    """)).all()
    return [float(r.v) for r in rows if r.v is not None]


def telemetry_history_daily_series(db: Session, column: str, days: int = 35) -> list[float]:
    """Same shape but for telemetry_history_daily."""
    SAFE_COLS = {
        "active_devices", "engaged_devices", "total_events", "error_events",
        "session_count", "successful_sessions", "avg_cook_temp", "avg_rssi",
    }
    if column not in SAFE_COLS:
        raise ValueError(f"refusing to query unknown telemetry column: {column!r}")
    rows = db.execute(text(f"""
        SELECT {column}::float AS v
        FROM telemetry_history_daily
        WHERE business_date >= CURRENT_DATE - INTERVAL '{int(days)} days'
          AND business_date < CURRENT_DATE
          AND {column} IS NOT NULL
        ORDER BY business_date
    """)).all()
    return [float(r.v) for r in rows]


def two_window_split(samples: list[float], current_window_days: int = 7) -> tuple[float, float]:
    """Split a series into (current_window_avg, prior_window_avg)."""
    if len(samples) < current_window_days * 2:
        if not samples:
            return 0.0, 0.0
        # Fall back to mean(last_N) vs mean(everything-before)
        cur_n = max(1, min(current_window_days, len(samples) // 2 or 1))
        cur = samples[-cur_n:]
        prior = samples[:-cur_n] or [0.0]
    else:
        cur = samples[-current_window_days:]
        prior = samples[-(current_window_days * 2):-current_window_days]
    return mean(cur), mean(prior) if prior else 0.0
