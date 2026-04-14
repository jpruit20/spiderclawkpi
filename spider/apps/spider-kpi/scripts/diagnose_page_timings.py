#!/usr/bin/env python3
"""Time every service call that Command Center and Marketing make on page load,
bypassing the FastAPI auth layer so we isolate DB/compute cost from framework
overhead.

Usage on the droplet:
    cd /opt/spiderclawkpi/spider/apps/spider-kpi
    .venv/bin/python scripts/diagnose_page_timings.py
"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "backend"))

from app.db.session import SessionLocal  # noqa: E402
from sqlalchemy import select  # noqa: E402


def _time(label: str, fn) -> None:
    t0 = time.monotonic()
    try:
        result = fn()
        elapsed = time.monotonic() - t0
        size_hint = ""
        if isinstance(result, dict):
            size_hint = f"  (keys={len(result)})"
        elif isinstance(result, list):
            size_hint = f"  (rows={len(result)})"
        print(f"{elapsed:8.3f}s  {label}{size_hint}")
    except Exception:
        elapsed = time.monotonic() - t0
        print(f"{elapsed:8.3f}s  {label}  !! ERROR")
        traceback.print_exc()


def main() -> int:
    db = SessionLocal()
    try:
        print("== Command Center + Marketing service timings ==\n")

        from app.services.overview import build_overview
        from app.services.issue_radar import build_issue_radar, read_cached_issue_radar
        from app.services.social_listening import (
            get_brand_pulse,
            get_market_intelligence,
            get_youtube_performance,
            get_social_trends,
        )
        from app.services.telemetry import summarize_telemetry
        from app.services.clarity_analytics import get_ux_friction_report
        from app.models import KPIDaily, ShopifyOrderDaily, ShopifyAnalyticsDaily, TWSummaryDaily

        _time("build_overview(db)", lambda: build_overview(db))
        _time("read_cached_issue_radar(db)", lambda: read_cached_issue_radar(db))
        _time("get_brand_pulse(db, days=30)", lambda: get_brand_pulse(db, days=30))
        _time("get_market_intelligence(db, days=30)", lambda: get_market_intelligence(db, days=30))
        _time("get_youtube_performance(db, days=30)", lambda: get_youtube_performance(db, days=30))
        _time("get_social_trends(db, days=30)", lambda: get_social_trends(db, days=30))
        _time("summarize_telemetry(db)", lambda: summarize_telemetry(db))
        _time("get_ux_friction_report(db)", lambda: get_ux_friction_report(db))

        # Deci overview — import locally because the module path may vary
        try:
            from app.api.routes.deci import build_division_overview  # type: ignore
            _time("build_division_overview(db)", lambda: build_division_overview(db))
        except Exception:
            # Fallback: skip quietly if the symbol isn't available
            pass

        print("\n== Raw unbounded table sizes (informational) ==")
        for Model, label in (
            (KPIDaily, "kpi_daily"),
            (ShopifyOrderDaily, "shopify_orders_daily"),
            (ShopifyAnalyticsDaily, "shopify_analytics_daily"),
            (TWSummaryDaily, "tw_summary_daily"),
        ):
            count = db.execute(select(Model)).scalars().all()
            print(f"  {label:30s} {len(count):>8d} rows")

        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
