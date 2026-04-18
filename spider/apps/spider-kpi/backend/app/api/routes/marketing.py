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


def _sum_kpi_intraday_clipped(
    db: Session, business_date_et: date, elapsed_hours_et: int
) -> dict[str, float]:
    """Sum KPIIntraday buckets whose bucket_start falls within
    ``business_date_et`` (interpreted in ET) up to ``elapsed_hours_et``
    hours past that day's midnight ET.

    Uses UTC ranges under the hood because ``bucket_start`` is stored
    tz-aware (UTC). Business-date boundaries are midnight ET.
    """
    day_start_et = datetime.combine(business_date_et, datetime.min.time(), tzinfo=BUSINESS_TZ)
    start_utc = day_start_et.astimezone(timezone.utc)
    end_utc = (day_start_et + timedelta(hours=elapsed_hours_et)).astimezone(timezone.utc)
    row = db.execute(
        select(
            func.coalesce(func.sum(KPIIntraday.revenue), 0.0).label("revenue"),
            func.coalesce(func.sum(KPIIntraday.orders), 0).label("orders"),
            func.coalesce(func.sum(KPIIntraday.sessions), 0.0).label("sessions"),
        ).where(KPIIntraday.bucket_start >= start_utc, KPIIntraday.bucket_start < end_utc)
    ).one()
    return {
        "revenue": float(row.revenue or 0.0),
        "orders": int(row.orders or 0),
        "sessions": float(row.sessions or 0.0),
    }


def _sum_tw_intraday_clipped(
    db: Session, business_date_et: date, elapsed_hours_et: int
) -> dict[str, float]:
    day_start_et = datetime.combine(business_date_et, datetime.min.time(), tzinfo=BUSINESS_TZ)
    start_utc = day_start_et.astimezone(timezone.utc)
    end_utc = (day_start_et + timedelta(hours=elapsed_hours_et)).astimezone(timezone.utc)
    row = db.execute(
        select(
            func.coalesce(func.sum(TWSummaryIntraday.revenue), 0.0).label("revenue"),
            func.coalesce(func.sum(TWSummaryIntraday.ad_spend), 0.0).label("ad_spend"),
        ).where(
            TWSummaryIntraday.bucket_start >= start_utc,
            TWSummaryIntraday.bucket_start < end_utc,
        )
    ).one()
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
    is set, the ``end_d`` day is excluded from the daily sum and
    replaced with the intraday (hour-clipped) contribution instead —
    so "today through 2pm" is apples-to-apples with "yesterday
    through 2pm" after the same treatment.
    """
    if trim_last_day_to_hours is None:
        return _sum_kpi_daily(db, start_d, end_d)

    # Sum complete days (everything before the trimmed day).
    if start_d < end_d:
        complete = _sum_kpi_daily(db, start_d, end_d - timedelta(days=1))
    else:
        complete = {"revenue": 0.0, "orders": 0, "sessions": 0.0, "ad_spend": 0.0}

    intraday = _sum_kpi_intraday_clipped(db, end_d, trim_last_day_to_hours)
    tw_intra = _sum_tw_intraday_clipped(db, end_d, trim_last_day_to_hours)

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
