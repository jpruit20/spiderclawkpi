"""Seasonality engine — computes per-metric, per-day-of-year historical
distributions and answers "is today running hot or cold?" for any metric.

Design (2026-04-19, first piece of the company-lore surface):

For every metric we track daily (revenue, orders, sessions, ad_spend,
active_devices, session_count, tickets_created), we walk the full
history and group observations by day-of-year (1-366). For each (metric,
DoY) bucket we compute p10 / p25 / p50 / p75 / p90 + mean + stddev.

The result lets every chart answer "where does today's value fit in
the last N years' distribution for this same day-of-year?" — a much
richer interpretation than week-over-week deltas, especially for a
highly seasonal business (grilling hardware).

When current-year data for a DoY is present in the source, it's
EXCLUDED from the baseline sample so we're always comparing "today"
against PRIOR years, not against itself.
"""
from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import SeasonalityBaseline


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Metric registry — the canonical list + their source table/column mappings.
# Adding a metric: append an entry here, run `rebuild_baselines`, done.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MetricSpec:
    name: str              # canonical name used by API + frontend
    source_table: str      # source relation
    source_column: str     # column to pull
    date_column: str       # date column in the source table
    # Optional SQL post-filter (e.g. exclude rows where the source
    # considers the value "partial" or "not yet materialized"). Applied
    # with AND.
    extra_filter: Optional[str] = None


METRICS: list[MetricSpec] = [
    MetricSpec("revenue",             "kpi_daily",                "revenue",              "business_date"),
    MetricSpec("orders",              "kpi_daily",                "orders",               "business_date"),
    MetricSpec("sessions",            "kpi_daily",                "sessions",             "business_date"),
    MetricSpec("ad_spend",            "kpi_daily",                "ad_spend",             "business_date"),
    MetricSpec("conversion_rate",     "kpi_daily",                "conversion_rate",      "business_date"),
    MetricSpec("active_devices",      "telemetry_history_daily",  "active_devices",       "business_date"),
    MetricSpec("session_count",       "telemetry_history_daily",  "session_count",        "business_date"),
    MetricSpec("tickets_created",     "freshdesk_tickets_daily",  "tickets_created",      "business_date"),
]


def _metric_by_name(name: str) -> Optional[MetricSpec]:
    for m in METRICS:
        if m.name == name:
            return m
    return None


# ---------------------------------------------------------------------------
# Build baselines — walks history, groups by DoY, upserts rows.
# ---------------------------------------------------------------------------

def _load_history(
    db: Session, spec: MetricSpec, exclude_year: Optional[int] = None
) -> list[tuple[date, float]]:
    """Return [(date, value), ...] for this metric across all history.
    Caller decides whether to exclude the current year."""
    where_clauses = [f"{spec.source_column} IS NOT NULL"]
    params: dict[str, Any] = {}
    if spec.extra_filter:
        where_clauses.append(spec.extra_filter)
    if exclude_year is not None:
        where_clauses.append(f"EXTRACT(year FROM {spec.date_column}) <> :exclude_year")
        params["exclude_year"] = exclude_year

    sql = text(
        f"SELECT {spec.date_column} AS d, {spec.source_column}::float AS v "
        f"FROM {spec.source_table} "
        f"WHERE {' AND '.join(where_clauses)} "
        f"ORDER BY {spec.date_column}"
    )
    rows = db.execute(sql, params).all()
    return [(r.d, float(r.v)) for r in rows if r.v is not None]


def _percentiles(values: list[float]) -> dict[str, Optional[float]]:
    n = len(values)
    if n == 0:
        return {k: None for k in ("p10", "p25", "p50", "p75", "p90", "mean", "stddev")}
    if n == 1:
        v = values[0]
        return {"p10": v, "p25": v, "p50": v, "p75": v, "p90": v, "mean": v, "stddev": 0.0}
    s = sorted(values)

    def _pct(p: float) -> float:
        # linear-interp percentile, 0 <= p <= 100
        k = (n - 1) * (p / 100.0)
        lo, hi = int(k), min(int(k) + 1, n - 1)
        frac = k - lo
        return s[lo] * (1 - frac) + s[hi] * frac

    return {
        "p10": _pct(10),
        "p25": _pct(25),
        "p50": _pct(50),
        "p75": _pct(75),
        "p90": _pct(90),
        "mean": sum(values) / n,
        "stddev": statistics.stdev(values) if n >= 2 else 0.0,
    }


def rebuild_baselines_for_metric(db: Session, spec: MetricSpec, *, exclude_current_year: bool = True) -> int:
    """Recompute all DoY rows for one metric. Returns rows written."""
    current_year = datetime.now(timezone.utc).year if exclude_current_year else None
    history = _load_history(db, spec, exclude_year=current_year)
    if not history:
        logger.warning("no history for %s, skipping", spec.name)
        return 0

    # Group: day_of_year -> list of (year, value)
    grouped: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for d, v in history:
        doy = d.timetuple().tm_yday
        grouped[doy].append((d.year, v))

    now = datetime.now(timezone.utc)
    written = 0
    for doy, samples in sorted(grouped.items()):
        values = [v for _y, v in samples]
        pcts = _percentiles(values)
        iso_week = date(2024, 1, 1).fromordinal(date(2024, 1, 1).toordinal() + doy - 1).isocalendar().week
        # ^^ 2024 is a leap year, so day_of_year 1..366 all map cleanly
        month = date(2024, 1, 1).fromordinal(date(2024, 1, 1).toordinal() + doy - 1).month
        year_samples = {str(y): v for y, v in samples}

        existing = db.execute(
            select(SeasonalityBaseline).where(
                SeasonalityBaseline.metric_name == spec.name,
                SeasonalityBaseline.day_of_year == doy,
            )
        ).scalars().first()
        if existing is None:
            existing = SeasonalityBaseline(
                metric_name=spec.name,
                metric_source=f"{spec.source_table}.{spec.source_column}",
                day_of_year=doy,
                iso_week=iso_week,
                month=month,
                year_count=0,
                sample_size=0,
            )
            db.add(existing)
        existing.metric_source = f"{spec.source_table}.{spec.source_column}"
        existing.iso_week = iso_week
        existing.month = month
        existing.year_count = len({y for y, _ in samples})
        existing.sample_size = len(samples)
        existing.p10 = pcts["p10"]
        existing.p25 = pcts["p25"]
        existing.p50 = pcts["p50"]
        existing.p75 = pcts["p75"]
        existing.p90 = pcts["p90"]
        existing.mean = pcts["mean"]
        existing.stddev = pcts["stddev"]
        existing.year_samples_json = year_samples
        existing.computed_at = now
        written += 1

    db.flush()
    return written


def rebuild_all_baselines(db: Session) -> dict[str, int]:
    """Walk every registered metric; return {metric_name: rows_written}."""
    stats: dict[str, int] = {}
    for spec in METRICS:
        try:
            n = rebuild_baselines_for_metric(db, spec)
            stats[spec.name] = n
            logger.info("  rebuilt %s: %d DoY rows", spec.name, n)
        except Exception:
            logger.exception("failed to rebuild baselines for %s", spec.name)
            stats[spec.name] = -1
    db.commit()
    return stats


# ---------------------------------------------------------------------------
# Query helpers — the "is today running hot or cold?" interpretation layer.
# ---------------------------------------------------------------------------

@dataclass
class MetricContext:
    metric_name: str
    on_date: date
    day_of_year: int
    current_value: Optional[float]
    baseline: dict[str, Optional[float]]   # p10/p25/p50/p75/p90/mean/stddev
    year_count: int
    verdict: str          # running_very_hot | running_hot | normal | running_cold | running_very_cold | no_baseline
    percentile_rank: Optional[float]  # 0-1 — where current_value falls in historical distribution
    delta_vs_median_pct: Optional[float]  # +/- % vs p50


def _classify_verdict(value: float, p: dict[str, Optional[float]]) -> str:
    p10, p25, p75, p90 = p.get("p10"), p.get("p25"), p.get("p75"), p.get("p90")
    if p25 is None or p75 is None:
        return "no_baseline"
    if p90 is not None and value > p90:
        return "running_very_hot"
    if value > p75:
        return "running_hot"
    if p10 is not None and value < p10:
        return "running_very_cold"
    if value < p25:
        return "running_cold"
    return "normal"


def _percentile_rank(value: float, samples_json: dict[str, Any]) -> Optional[float]:
    values = [float(v) for v in samples_json.values() if v is not None]
    if not values:
        return None
    below = sum(1 for v in values if v < value)
    same = sum(1 for v in values if v == value)
    # Average-rank handling of ties — (below + same/2) / n
    return round((below + same / 2) / len(values), 3)


def metric_context(
    db: Session,
    metric_name: str,
    on_date: date,
    current_value: Optional[float] = None,
) -> Optional[MetricContext]:
    """Return the seasonal context for a metric on a given date.

    If ``current_value`` is omitted, it's fetched from the source table.
    Returns None if the metric isn't registered.
    """
    spec = _metric_by_name(metric_name)
    if spec is None:
        return None

    doy = on_date.timetuple().tm_yday

    row = db.execute(
        select(SeasonalityBaseline).where(
            SeasonalityBaseline.metric_name == metric_name,
            SeasonalityBaseline.day_of_year == doy,
        )
    ).scalars().first()

    if current_value is None:
        rr = db.execute(
            text(
                f"SELECT {spec.source_column}::float AS v FROM {spec.source_table} "
                f"WHERE {spec.date_column} = :d LIMIT 1"
            ),
            {"d": on_date},
        ).first()
        current_value = float(rr.v) if rr and rr.v is not None else None

    baseline = {
        "p10": getattr(row, "p10", None) if row else None,
        "p25": getattr(row, "p25", None) if row else None,
        "p50": getattr(row, "p50", None) if row else None,
        "p75": getattr(row, "p75", None) if row else None,
        "p90": getattr(row, "p90", None) if row else None,
        "mean": getattr(row, "mean", None) if row else None,
        "stddev": getattr(row, "stddev", None) if row else None,
    }
    year_count = row.year_count if row else 0
    samples = row.year_samples_json if row else {}

    verdict = "no_baseline"
    pct_rank: Optional[float] = None
    delta_pct: Optional[float] = None

    if current_value is not None and row is not None:
        verdict = _classify_verdict(current_value, baseline)
        pct_rank = _percentile_rank(current_value, samples)
        if baseline["p50"] and baseline["p50"] != 0:
            delta_pct = (current_value - baseline["p50"]) / baseline["p50"] * 100.0

    return MetricContext(
        metric_name=metric_name,
        on_date=on_date,
        day_of_year=doy,
        current_value=current_value,
        baseline=baseline,
        year_count=year_count,
        verdict=verdict,
        percentile_rank=pct_rank,
        delta_vs_median_pct=round(delta_pct, 2) if delta_pct is not None else None,
    )


def baselines_for_range(
    db: Session, metric_name: str, start: date, end: date
) -> list[dict[str, Any]]:
    """Return a list of {date, day_of_year, p10/p25/p50/p75/p90, ...} rows
    for every date in [start, end], suitable for rendering a baseline
    band overlay on a chart."""
    rows = db.execute(
        select(SeasonalityBaseline).where(SeasonalityBaseline.metric_name == metric_name)
    ).scalars().all()
    by_doy = {r.day_of_year: r for r in rows}

    out: list[dict[str, Any]] = []
    cur = start
    while cur <= end:
        doy = cur.timetuple().tm_yday
        r = by_doy.get(doy)
        out.append({
            "date": cur.isoformat(),
            "day_of_year": doy,
            "p10": r.p10 if r else None,
            "p25": r.p25 if r else None,
            "p50": r.p50 if r else None,
            "p75": r.p75 if r else None,
            "p90": r.p90 if r else None,
            "year_count": r.year_count if r else 0,
        })
        cur += timedelta(days=1)
    return out
