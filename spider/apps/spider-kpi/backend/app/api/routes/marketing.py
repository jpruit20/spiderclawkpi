"""Marketing division endpoints.

Grew out of the 2026-04-18 Triple Whale deep-dive: we needed channel-
level spend aggregation, hour-trimmed period comparisons, and funnel
clarity separate from the monolithic ``overview.py``. Living here means
adding/changing marketing surface doesn't risk the global overview API.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_dashboard_session
from app.models import KPIDaily, KPIIntraday, TWSummaryDaily, TWSummaryIntraday


logger = logging.getLogger(__name__)
BUSINESS_TZ = ZoneInfo("America/New_York")

router = APIRouter(
    prefix="/api/marketing",
    tags=["marketing"],
    dependencies=[Depends(require_dashboard_session)],
)


# Column-name → display label for the Marketing channel-mix card.
# Ordered by typical spend magnitude at Spider Grills so the stacked
# bar reads predictably (largest channels first); front-end may
# re-order by actual spend.
CHANNEL_COLUMNS: list[tuple[str, str]] = [
    ("facebook_spend", "Facebook"),
    ("google_spend", "Google"),
    ("tiktok_spend", "TikTok"),
    ("amazon_ads_spend", "Amazon"),
    ("pinterest_spend", "Pinterest"),
    ("snapchat_spend", "Snapchat"),
    ("bing_spend", "Bing"),
    ("twitter_spend", "Twitter/X"),
    ("reddit_spend", "Reddit"),
    ("linkedin_spend", "LinkedIn"),
    ("smsbump_spend", "SMSBump"),
    ("omnisend_spend", "Omnisend"),
    ("postscript_spend", "Postscript"),
    ("taboola_spend", "Taboola"),
    ("outbrain_spend", "Outbrain"),
    ("stackadapt_spend", "StackAdapt"),
    ("adroll_spend", "AdRoll"),
    ("impact_spend", "Impact"),
    ("custom_spend", "Custom/Other"),
]


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _resolve_window(
    start: Optional[str], end: Optional[str], default_days: int
) -> tuple[date, date]:
    end_d = _parse_date(end) or datetime.now(BUSINESS_TZ).date()
    start_d = _parse_date(start) or (end_d - timedelta(days=default_days - 1))
    if start_d > end_d:
        start_d, end_d = end_d, start_d
    return start_d, end_d


@router.get("/channel-mix")
def channel_mix(
    start: Optional[str] = Query(None, description="YYYY-MM-DD start (inclusive)"),
    end: Optional[str] = Query(None, description="YYYY-MM-DD end (inclusive)"),
    days: int = Query(30, ge=1, le=730, description="default window if start/end omitted"),
    compare_prior: bool = Query(True, description="include prior-period totals for delta"),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Per-channel ad-spend mix for the selected window, plus the
    prior period (same length, immediately before) so each channel
    can show a delta.

    Returns total spend, total revenue, MER (revenue / spend), and
    the channel breakdown as ``[{column, label, spend, share_pct,
    prior_spend, delta_pct}]`` sorted by descending current spend.
    """
    start_d, end_d = _resolve_window(start, end, days)
    window_days = (end_d - start_d).days + 1

    prior_end = start_d - timedelta(days=1)
    prior_start = prior_end - timedelta(days=window_days - 1)

    # Current window aggregate.
    cur_cols = [func.coalesce(func.sum(getattr(TWSummaryDaily, col)), 0.0).label(col)
                for col, _ in CHANNEL_COLUMNS]
    cur_row = db.execute(
        select(
            func.coalesce(func.sum(TWSummaryDaily.ad_spend), 0.0).label("ad_spend"),
            func.coalesce(func.sum(TWSummaryDaily.revenue), 0.0).label("revenue"),
            *cur_cols,
        ).where(
            TWSummaryDaily.business_date >= start_d,
            TWSummaryDaily.business_date <= end_d,
        )
    ).one()

    prior_row = None
    if compare_prior:
        prior_cols = [func.coalesce(func.sum(getattr(TWSummaryDaily, col)), 0.0).label(col)
                      for col, _ in CHANNEL_COLUMNS]
        prior_row = db.execute(
            select(
                func.coalesce(func.sum(TWSummaryDaily.ad_spend), 0.0).label("ad_spend"),
                func.coalesce(func.sum(TWSummaryDaily.revenue), 0.0).label("revenue"),
                *prior_cols,
            ).where(
                TWSummaryDaily.business_date >= prior_start,
                TWSummaryDaily.business_date <= prior_end,
            )
        ).one()

    # Blended ad spend may exceed the per-channel sum if TW returned
    # a blended value that included channels we haven't yet mapped;
    # use the bigger of the two as denominator so shares still make
    # sense against the headline number.
    per_channel_sum = sum(float(getattr(cur_row, col) or 0.0) for col, _ in CHANNEL_COLUMNS)
    total_spend = max(float(cur_row.ad_spend or 0.0), per_channel_sum)

    channels = []
    for col, label in CHANNEL_COLUMNS:
        cur_val = float(getattr(cur_row, col) or 0.0)
        prior_val = float(getattr(prior_row, col) or 0.0) if prior_row is not None else 0.0
        share = (cur_val / total_spend * 100.0) if total_spend > 0 else 0.0
        delta_pct: Optional[float] = None
        if prior_val > 0:
            delta_pct = (cur_val - prior_val) / prior_val * 100.0
        channels.append({
            "column": col,
            "label": label,
            "spend": round(cur_val, 2),
            "share_pct": round(share, 2),
            "prior_spend": round(prior_val, 2),
            "delta_pct": round(delta_pct, 1) if delta_pct is not None else None,
        })
    channels.sort(key=lambda c: c["spend"], reverse=True)

    # "Missing" bucket = blended ad_spend minus sum of typed channel
    # columns. Non-zero means TW reported blended spend that didn't
    # break down into any channel we've mapped — points to a channel
    # alias we should add.
    missing_bucket = max(0.0, float(cur_row.ad_spend or 0.0) - per_channel_sum)

    revenue = float(cur_row.revenue or 0.0)
    mer = revenue / total_spend if total_spend > 0 else None

    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "start": start_d.isoformat(),
            "end": end_d.isoformat(),
            "days": window_days,
        },
        "prior_window": {
            "start": prior_start.isoformat(),
            "end": prior_end.isoformat(),
            "days": window_days,
        } if compare_prior else None,
        "totals": {
            "ad_spend": round(total_spend, 2),
            "revenue": round(revenue, 2),
            "mer": round(mer, 3) if mer is not None else None,
            "unmapped_spend": round(missing_bucket, 2),
            "per_channel_sum": round(per_channel_sum, 2),
        },
        "channels": channels,
    }


# ───────────────────────────────────────────────────────────────────
# Period comparison with hour-trimming (issue #2 from Joseph 2026-04-18)
#
# Motivation: the Marketing page's comparison logic was summing whole
# KPIDaily rows. If the current window includes today at 2pm ET, it
# was comparing 14 hours of today vs 24 hours of yesterday — always
# making today look worse ("revenue down 40%" at noon, then magically
# up when the day closes). Apples-to-oranges.
#
# Fix: detect whether the current window includes a partial "today"
# (end == today ET AND current ET hour < 24). If so, trim the
# equivalent day(s) in the prior window to the same elapsed hours
# using KPIIntraday / TWSummaryIntraday, which we already materialize
# hourly. Returns both totals so the frontend can render an
# honest-comparison KPI strip.
# ───────────────────────────────────────────────────────────────────


def _sum_kpi_daily(db: Session, start_d: date, end_d: date) -> dict[str, float]:
    row = db.execute(
        select(
            func.coalesce(func.sum(KPIDaily.revenue), 0.0).label("revenue"),
            func.coalesce(func.sum(KPIDaily.orders), 0).label("orders"),
            func.coalesce(func.sum(KPIDaily.sessions), 0).label("sessions"),
            func.coalesce(func.sum(KPIDaily.ad_spend), 0.0).label("ad_spend"),
        ).where(KPIDaily.business_date >= start_d, KPIDaily.business_date <= end_d)
    ).one()
    return {
        "revenue": float(row.revenue or 0.0),
        "orders": int(row.orders or 0),
        "sessions": float(row.sessions or 0.0),
        "ad_spend": float(row.ad_spend or 0.0),
    }


def _latest_kpi_intraday_snapshot(
    db: Session, business_date_et: date, elapsed_hours_et: int
) -> dict[str, float]:
    """Return the latest KPIIntraday **snapshot** on ``business_date_et``
    at or before ``elapsed_hours_et`` past ET midnight.

    CRITICAL: kpi_intraday rows are *cumulative-to-date snapshots*
    (running totals of the day), NOT hourly increments. Summing them
    across the day inflates values Nx (where N = snapshot count). We
    pick the latest snapshot inside the hour cap and return its
    running totals as-of that point.

    If no snapshot exists for the day within the cap (common
    pre-materialize for early morning), return zeros so the caller
    can decide how to degrade gracefully.
    """
    day_start_et = datetime.combine(business_date_et, datetime.min.time(), tzinfo=BUSINESS_TZ)
    start_utc = day_start_et.astimezone(timezone.utc)
    end_utc = (day_start_et + timedelta(hours=elapsed_hours_et)).astimezone(timezone.utc)
    row = db.execute(
        select(
            KPIIntraday.revenue,
            KPIIntraday.orders,
            KPIIntraday.sessions,
        )
        .where(KPIIntraday.bucket_start >= start_utc, KPIIntraday.bucket_start < end_utc)
        .order_by(KPIIntraday.bucket_start.desc())
        .limit(1)
    ).first()
    if row is None:
        return {"revenue": 0.0, "orders": 0, "sessions": 0.0}
    return {
        "revenue": float(row.revenue or 0.0),
        "orders": int(row.orders or 0),
        "sessions": float(row.sessions or 0.0),
    }


def _latest_tw_intraday_snapshot(
    db: Session, business_date_et: date, elapsed_hours_et: int
) -> dict[str, float]:
    """Same snapshot semantics as KPIIntraday for TWSummaryIntraday —
    each bucket is cumulative-to-date, so we take the latest within
    the hour cap rather than summing."""
    day_start_et = datetime.combine(business_date_et, datetime.min.time(), tzinfo=BUSINESS_TZ)
    start_utc = day_start_et.astimezone(timezone.utc)
    end_utc = (day_start_et + timedelta(hours=elapsed_hours_et)).astimezone(timezone.utc)
    row = db.execute(
        select(
            TWSummaryIntraday.revenue,
            TWSummaryIntraday.ad_spend,
        )
        .where(
            TWSummaryIntraday.bucket_start >= start_utc,
            TWSummaryIntraday.bucket_start < end_utc,
        )
        .order_by(TWSummaryIntraday.bucket_start.desc())
        .limit(1)
    ).first()
    if row is None:
        return {"revenue": 0.0, "ad_spend": 0.0}
    return {
        "revenue": float(row.revenue or 0.0),
        "ad_spend": float(row.ad_spend or 0.0),
    }


def _aggregate_window(
    db: Session,
    start_d: date,
    end_d: date,
    trim_last_day_to_hours: Optional[int],
) -> dict[str, float]:
    """Aggregate KPIs for a date range. If ``trim_last_day_to_hours``
    is set, ``end_d`` is treated as the "trimmed" day and its
    contribution comes from the latest intraday **snapshot** at or
    before the hour cap (kpi_intraday and tw_summary_intraday store
    running totals per bucket, not hourly deltas — summing them
    would Nx-inflate the number). Days before ``end_d`` are summed
    from kpi_daily as usual.
    """
    if trim_last_day_to_hours is None:
        return _sum_kpi_daily(db, start_d, end_d)

    # Sum complete days preceding the trimmed day.
    if start_d < end_d:
        complete = _sum_kpi_daily(db, start_d, end_d - timedelta(days=1))
    else:
        complete = {"revenue": 0.0, "orders": 0, "sessions": 0.0, "ad_spend": 0.0}

    # Latest running-total snapshot for end_d at/before the hour cap.
    intraday = _latest_kpi_intraday_snapshot(db, end_d, trim_last_day_to_hours)
    tw_intra = _latest_tw_intraday_snapshot(db, end_d, trim_last_day_to_hours)

    return {
        "revenue": complete["revenue"] + intraday["revenue"],
        "orders": int(complete["orders"]) + int(intraday["orders"]),
        "sessions": complete["sessions"] + intraday["sessions"],
        "ad_spend": complete["ad_spend"] + tw_intra["ad_spend"],
    }


@router.get("/period-compare")
def period_compare(
    start: Optional[str] = Query(None, description="YYYY-MM-DD start (inclusive)"),
    end: Optional[str] = Query(None, description="YYYY-MM-DD end (inclusive, default today ET)"),
    days: int = Query(30, ge=1, le=730, description="default window if start/end omitted"),
    mode: str = Query("prior_period", description="prior_period | same_day_last_week"),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Revenue / orders / sessions / ad-spend comparison with
    hour-trimming when the current window ends today ET.

    The prior window's last-equivalent day is clipped to the same
    elapsed-hours-into-day so today-so-far vs yesterday-so-far (or
    same-day-last-week-so-far) is a fair comparison.
    """
    today_et = datetime.now(BUSINESS_TZ).date()
    now_et = datetime.now(BUSINESS_TZ)
    start_d, end_d = _resolve_window(start, end, days)

    # Hour-trim applies only if end==today AND we're mid-day ET. A full
    # completed day (hour 24 after midnight ET, i.e. next day) doesn't
    # need trimming.
    is_partial_today = (end_d == today_et) and now_et.hour < 23
    elapsed_hours = (now_et.hour + 1) if is_partial_today else None  # +1 so 14:30 → bucket 15 inclusive

    window_days = (end_d - start_d).days + 1

    if mode == "same_day_last_week":
        prior_start = start_d - timedelta(days=7)
        prior_end = end_d - timedelta(days=7)
    elif mode == "yoy":
        # Shift the window back 365 days. Not leap-year aware — with
        # enough year-over-year swing this is close enough for KPI
        # deltas and avoids edge cases around Feb 29.
        prior_start = start_d - timedelta(days=365)
        prior_end = end_d - timedelta(days=365)
    else:
        prior_end = start_d - timedelta(days=1)
        prior_start = prior_end - timedelta(days=window_days - 1)

    current = _aggregate_window(db, start_d, end_d, elapsed_hours)
    prior = _aggregate_window(db, prior_start, prior_end, elapsed_hours)

    def _safe_pct(cur: float, base: float) -> Optional[float]:
        return ((cur - base) / base * 100.0) if base else None

    label_suffix = ""
    if elapsed_hours is not None:
        label_suffix = f" (through {now_et:%-I:%M %p} ET)"

    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "window": {
            "start": start_d.isoformat(),
            "end": end_d.isoformat(),
            "days": window_days,
            "label_suffix": label_suffix,
        },
        "prior_window": {
            "start": prior_start.isoformat(),
            "end": prior_end.isoformat(),
            "days": window_days,
        },
        "elapsed_hours_et": elapsed_hours,
        "hour_trim_applied": elapsed_hours is not None,
        "current": current,
        "prior": prior,
        "deltas": {
            "revenue_pct": _safe_pct(current["revenue"], prior["revenue"]),
            "orders_pct": _safe_pct(current["orders"], prior["orders"]),
            "sessions_pct": _safe_pct(current["sessions"], prior["sessions"]),
            "ad_spend_pct": _safe_pct(current["ad_spend"], prior["ad_spend"]),
        },
    }


# ───────────────────────────────────────────────────────────────────
# Channel trends — daily spend series per channel over a window so the
# Marketing page can render sparklines alongside the channel-mix card.
# Catches patterns the mix card alone misses: "we ramped TikTok the
# last three weeks but quietly killed Pinterest" is invisible when
# you only look at the window total.
# ───────────────────────────────────────────────────────────────────


@router.get("/channel-trends")
def channel_trends(
    days: int = Query(30, ge=7, le=180),
    min_spend_total: float = Query(
        10.0, ge=0.0,
        description="drop channels whose total spend over the window is below this threshold",
    ),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    today = datetime.now(BUSINESS_TZ).date()
    start_d = today - timedelta(days=days - 1)

    col_select = [getattr(TWSummaryDaily, col) for col, _ in CHANNEL_COLUMNS]
    rows = db.execute(
        select(TWSummaryDaily.business_date, *col_select)
        .where(
            TWSummaryDaily.business_date >= start_d,
            TWSummaryDaily.business_date <= today,
        )
        .order_by(TWSummaryDaily.business_date)
    ).all()

    # Pivot row-per-day → column-per-channel with a full date axis so
    # the frontend can plot zero-spend days (a real "paused" signal),
    # not skip them.
    date_axis = [(start_d + timedelta(days=i)).isoformat() for i in range(days)]
    index_by_date = {d: i for i, d in enumerate(date_axis)}

    series: dict[str, list[float]] = {col: [0.0] * days for col, _ in CHANNEL_COLUMNS}
    for r in rows:
        idx = index_by_date.get(r.business_date.isoformat())
        if idx is None:
            continue
        for col, _ in CHANNEL_COLUMNS:
            val = getattr(r, col, 0.0) or 0.0
            series[col][idx] = float(val)

    channels = []
    for col, label in CHANNEL_COLUMNS:
        daily = series[col]
        total = sum(daily)
        if total < min_spend_total:
            continue
        # Simple split: first-half vs second-half average to detect
        # ramp-up/wind-down patterns without pulling in a linregress.
        mid = days // 2
        first_half = daily[:mid]
        second_half = daily[mid:]
        first_avg = sum(first_half) / max(len(first_half), 1)
        second_avg = sum(second_half) / max(len(second_half), 1)
        trend_pct = ((second_avg - first_avg) / first_avg * 100.0) if first_avg > 0 else None
        recent_7d = sum(daily[-7:])
        prior_7d = sum(daily[-14:-7]) if days >= 14 else 0.0
        recent_delta_pct = ((recent_7d - prior_7d) / prior_7d * 100.0) if prior_7d > 0 else None
        channels.append({
            "column": col,
            "label": label,
            "total_spend": round(total, 2),
            "daily": [round(v, 2) for v in daily],
            "first_half_avg": round(first_avg, 2),
            "second_half_avg": round(second_avg, 2),
            "trend_pct": round(trend_pct, 1) if trend_pct is not None else None,
            "recent_7d_spend": round(recent_7d, 2),
            "recent_7d_delta_pct": round(recent_delta_pct, 1) if recent_delta_pct is not None else None,
        })

    channels.sort(key=lambda c: c["total_spend"], reverse=True)

    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": start_d.isoformat(), "end": today.isoformat(), "days": days},
        "date_axis": date_axis,
        "channels": channels,
    }


# ───────────────────────────────────────────────────────────────────
# Pacing + dormant-channel detection — answers "are we spending at a
# healthy rate this week vs recent weeks, and is any channel that
# used to be on now quietly off?". Replaces the need for a manual
# budget-config surface until one exists.
# ───────────────────────────────────────────────────────────────────


@router.get("/pacing")
def pacing(
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    today = datetime.now(BUSINESS_TZ).date()
    # "This week" = trailing 7 days ending today (not ISO week — avoids
    # a Monday that has only one day of data making the whole week
    # look underspent).
    week_start = today - timedelta(days=6)
    weeks_back = 4
    baseline_start = today - timedelta(days=7 * (weeks_back + 1) - 1)
    baseline_end = week_start - timedelta(days=1)

    # This week totals.
    channel_cols = [getattr(TWSummaryDaily, col) for col, _ in CHANNEL_COLUMNS]
    this_week_row = db.execute(
        select(
            func.coalesce(func.sum(TWSummaryDaily.ad_spend), 0.0).label("ad_spend"),
            *[func.coalesce(func.sum(c), 0.0).label(c.key) for c in channel_cols],
        ).where(
            TWSummaryDaily.business_date >= week_start,
            TWSummaryDaily.business_date <= today,
        )
    ).one()

    # Trailing 4 weeks aggregate (not including this week).
    baseline_row = db.execute(
        select(
            func.coalesce(func.sum(TWSummaryDaily.ad_spend), 0.0).label("ad_spend"),
            *[func.coalesce(func.sum(c), 0.0).label(c.key) for c in channel_cols],
        ).where(
            TWSummaryDaily.business_date >= baseline_start,
            TWSummaryDaily.business_date <= baseline_end,
        )
    ).one()

    # Days of this-week data actually present — projection needs this
    # because today is likely mid-day. Count distinct business_dates
    # with any spend so weekends with $0 spend don't inflate the avg.
    days_present = db.execute(
        select(func.count(func.distinct(TWSummaryDaily.business_date)))
        .where(
            TWSummaryDaily.business_date >= week_start,
            TWSummaryDaily.business_date <= today,
            TWSummaryDaily.ad_spend > 0,
        )
    ).scalar() or 0

    this_week_spend = float(this_week_row.ad_spend or 0.0)
    baseline_spend = float(baseline_row.ad_spend or 0.0)
    baseline_weekly_avg = baseline_spend / weeks_back if weeks_back > 0 else 0.0
    baseline_daily_avg = baseline_weekly_avg / 7.0 if baseline_weekly_avg > 0 else 0.0

    daily_avg_so_far = this_week_spend / days_present if days_present > 0 else 0.0
    projected_week_end = daily_avg_so_far * 7.0 if days_present > 0 else 0.0

    pacing_delta_pct: Optional[float] = None
    if baseline_weekly_avg > 0:
        pacing_delta_pct = (projected_week_end - baseline_weekly_avg) / baseline_weekly_avg * 100.0

    # Dormant channels: had meaningful spend in the baseline (>$100/wk
    # avg), but $0 in the last 7 days. This catches "paused" channels
    # better than a pure 0-vs-0 check.
    dormant = []
    active = []
    for col, label in CHANNEL_COLUMNS:
        this_val = float(getattr(this_week_row, col, 0.0) or 0.0)
        base_val = float(getattr(baseline_row, col, 0.0) or 0.0)
        base_weekly = base_val / weeks_back if weeks_back > 0 else 0.0
        if base_weekly >= 100.0 and this_val == 0.0:
            dormant.append({
                "column": col, "label": label,
                "baseline_weekly_spend": round(base_weekly, 2),
                "this_week_spend": 0.0,
            })
        elif this_val > 0 or base_weekly > 0:
            delta_pct = ((this_val - base_weekly) / base_weekly * 100.0) if base_weekly > 0 else None
            active.append({
                "column": col, "label": label,
                "this_week_spend": round(this_val, 2),
                "baseline_weekly_spend": round(base_weekly, 2),
                "delta_pct": round(delta_pct, 1) if delta_pct is not None else None,
            })
    active.sort(key=lambda c: c["this_week_spend"], reverse=True)

    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "week_start": week_start.isoformat(),
            "today": today.isoformat(),
            "days_present": int(days_present),
        },
        "baseline_window": {
            "start": baseline_start.isoformat(),
            "end": baseline_end.isoformat(),
            "weeks": weeks_back,
        },
        "this_week_spend": round(this_week_spend, 2),
        "baseline_weekly_avg": round(baseline_weekly_avg, 2),
        "baseline_daily_avg": round(baseline_daily_avg, 2),
        "daily_avg_so_far": round(daily_avg_so_far, 2),
        "projected_week_end": round(projected_week_end, 2),
        "pacing_delta_pct": round(pacing_delta_pct, 1) if pacing_delta_pct is not None else None,
        "dormant_channels": dormant,
        "active_channels": active,
    }


# ───────────────────────────────────────────────────────────────────
# MER health — compute daily blended MER (KPIDaily.revenue / TW
# ad_spend) over a 90-day window, build p10/p50/p90 band, and flag
# whether the most-recent completed day sits outside the band.
# ───────────────────────────────────────────────────────────────────


@router.get("/mer-health")
def mer_health(
    days: int = Query(90, ge=28, le=365),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    today = datetime.now(BUSINESS_TZ).date()
    start_d = today - timedelta(days=days - 1)

    # Join KPIDaily revenue with TW ad_spend on business_date; take
    # daily MER only for days with both values > 0 so we don't pollute
    # the band with boot-up zeroes.
    rows = db.execute(
        select(
            KPIDaily.business_date,
            KPIDaily.revenue.label("revenue"),
            TWSummaryDaily.ad_spend.label("ad_spend"),
        )
        .join(
            TWSummaryDaily,
            TWSummaryDaily.business_date == KPIDaily.business_date,
        )
        .where(KPIDaily.business_date >= start_d, KPIDaily.business_date <= today)
        .order_by(KPIDaily.business_date)
    ).all()

    daily = []
    for r in rows:
        rev = float(r.revenue or 0.0)
        spend = float(r.ad_spend or 0.0)
        if spend > 0 and rev > 0:
            daily.append({
                "date": r.business_date.isoformat(),
                "revenue": round(rev, 2),
                "ad_spend": round(spend, 2),
                "mer": round(rev / spend, 3),
            })

    mer_values = sorted([d["mer"] for d in daily])
    n = len(mer_values)
    def _pct(p: float) -> Optional[float]:
        if n == 0:
            return None
        idx = min(max(int(round(p * (n - 1))), 0), n - 1)
        return round(mer_values[idx], 3)

    p10, p50, p90 = _pct(0.10), _pct(0.50), _pct(0.90)

    latest = daily[-1] if daily else None
    # "Latest complete day" gate: if the last row is today and hour is
    # still early, latest MER may be misleading. Caller can pair with
    # the period-compare endpoint for intra-day. Here we just surface
    # the freshest daily value.
    latest_mer = latest["mer"] if latest else None
    band_state: str = "unknown"
    if latest_mer is not None and p10 is not None and p90 is not None:
        if latest_mer > p90:
            band_state = "above_band"
        elif latest_mer < p10:
            band_state = "below_band"
        else:
            band_state = "in_band"

    # Trailing-7d MER (good for "this week is running hot/cold")
    recent = daily[-7:] if len(daily) >= 7 else daily
    recent_rev = sum(d["revenue"] for d in recent)
    recent_spend = sum(d["ad_spend"] for d in recent)
    recent_mer = round(recent_rev / recent_spend, 3) if recent_spend > 0 else None

    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": start_d.isoformat(), "end": today.isoformat(), "days": days},
        "observations": n,
        "band": {"p10": p10, "p50": p50, "p90": p90},
        "latest": latest,
        "latest_band_state": band_state,
        "trailing_7d_mer": recent_mer,
        "daily": daily,
    }
