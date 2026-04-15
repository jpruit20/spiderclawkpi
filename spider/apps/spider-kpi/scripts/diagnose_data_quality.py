#!/usr/bin/env python3
"""One-shot diagnostic for the data-correctness audit.

Answers three questions:
  1. What shapes does error_codes_json actually take before vs after
     the Apr 9 stream regime change? (explains 100% error rate)
  2. Is GA4 configured and reachable? (gates the real sessions fix)
  3. What does today's kpi_intraday vs kpi_daily show?
     (explains the $6,974 vs $8,913 revenue gap)

Plus a compact source-sync-runs report for the broader audit.

Usage on the droplet:
    cd /opt/spiderclawkpi/spider/apps/spider-kpi
    .venv/bin/python scripts/diagnose_data_quality.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "backend"))

from app.db.session import SessionLocal  # noqa: E402
from sqlalchemy import text  # noqa: E402


def hr(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main() -> int:
    db = SessionLocal()
    try:
        # =====================================================================
        # 1. error_codes_json shape distribution
        # =====================================================================
        hr("1. telemetry_stream_events.error_codes_json shape distribution")
        row = db.execute(text("""
            SELECT
              COUNT(*) AS total,
              COUNT(*) FILTER (WHERE error_codes_json = '[]'::jsonb) AS empty_list,
              COUNT(*) FILTER (WHERE error_codes_json = '[0]'::jsonb) AS only_zero,
              COUNT(*) FILTER (WHERE error_codes_json != '[]'::jsonb
                                AND error_codes_json != '[0]'::jsonb) AS counted_as_error,
              COUNT(*) FILTER (WHERE error_codes_json IS NULL) AS is_null
            FROM telemetry_stream_events
        """)).mappings().one()
        print(f"  total rows                 : {row['total']:>10,}")
        print(f"  = '[]' (empty list)        : {row['empty_list']:>10,}")
        print(f"  = '[0]' (one probe, OK)    : {row['only_zero']:>10,}")
        print(f"  anything else (COUNTED!)   : {row['counted_as_error']:>10,}  <-- this is driving error_events")
        print(f"  NULL                       : {row['is_null']:>10,}")

        print("\n  -- top 15 distinct error_codes_json values 'counted as error' --")
        rows = db.execute(text("""
            SELECT error_codes_json::text AS shape, COUNT(*) AS n
            FROM telemetry_stream_events
            WHERE error_codes_json != '[]'::jsonb
              AND error_codes_json != '[0]'::jsonb
            GROUP BY error_codes_json::text
            ORDER BY n DESC
            LIMIT 15
        """)).mappings().all()
        for r in rows:
            print(f"  {r['n']:>10,}  {r['shape']}")

        print("\n  -- same shapes, but asking 'does it contain any NON-zero code?' --")
        rows = db.execute(text("""
            SELECT
              COUNT(*) FILTER (
                WHERE EXISTS (
                  SELECT 1 FROM jsonb_array_elements(error_codes_json) AS elem
                  WHERE (elem)::text::int != 0
                )
              ) AS truly_has_nonzero_error,
              COUNT(*) FILTER (
                WHERE NOT EXISTS (
                  SELECT 1 FROM jsonb_array_elements(error_codes_json) AS elem
                  WHERE (elem)::text::int != 0
                ) AND jsonb_array_length(error_codes_json) > 0
              ) AS all_zeros_but_nonempty
            FROM telemetry_stream_events
            WHERE error_codes_json IS NOT NULL
              AND jsonb_typeof(error_codes_json) = 'array'
        """)).mappings().one()
        print(f"  truly has non-zero error   : {rows['truly_has_nonzero_error']:>10,}")
        print(f"  all zeros but non-empty    : {rows['all_zeros_but_nonempty']:>10,}  <-- these are false positives")

        # =====================================================================
        # 2. GA4 config check
        # =====================================================================
        hr("2. GA4 configuration")
        from app.core.config import settings  # type: ignore
        ga4_errors = settings.ga4_validation_errors()
        print(f"  ga4_project_id configured  : {bool(settings.ga4_project_id)}")
        print(f"  ga4_property_id configured : {bool(settings.ga4_property_id)}")
        print(f"  ga4_client_email configured: {bool(settings.ga4_client_email)}  ({settings.masked_ga4_client_email()})")
        print(f"  ga4_private_key configured : {bool(settings.ga4_private_key)}")
        print(f"  validation errors          : {ga4_errors or 'none'}")

        if not ga4_errors:
            print("\n  -- attempting a 7-day ga4_debug_self_check --")
            try:
                from app.ingestion.connectors.ga4 import ga4_debug_self_check  # type: ignore
                result = ga4_debug_self_check(days=7)
                for k, v in result.items():
                    if k == 'rows':
                        print(f"    rows ({len(v)} returned, first 3):")
                        for r in v[:3]:
                            print(f"      {r}")
                    else:
                        print(f"    {k}: {v}")
            except Exception as exc:
                print(f"    FAILED: {type(exc).__name__}: {exc}")

        # =====================================================================
        # 3. today's kpi_intraday vs kpi_daily
        # =====================================================================
        hr("3. today's revenue / sessions path")
        today = date.today()
        print(f"  date.today() = {today.isoformat()}")
        print()
        print("  -- kpi_daily.business_date = today --")
        row = db.execute(text("""
            SELECT business_date, revenue, sessions, orders, conversion_rate, tickets_created
            FROM kpi_daily WHERE business_date = :today
        """), {"today": today}).mappings().first()
        print(f"    {dict(row) if row else '(no row)'}")

        print("\n  -- most recent kpi_intraday rows (latest 5) --")
        rows = db.execute(text("""
            SELECT bucket_start, revenue, sessions, orders
            FROM kpi_intraday ORDER BY bucket_start DESC LIMIT 5
        """)).mappings().all()
        for r in rows:
            print(f"    {dict(r)}")

        print("\n  -- shopify_orders_daily for today --")
        row = db.execute(text("""
            SELECT business_date, orders, revenue, refunds
            FROM shopify_orders_daily WHERE business_date = :today
        """), {"today": today}).mappings().first()
        print(f"    {dict(row) if row else '(no row)'}")

        print("\n  -- tw_summary_daily for today --")
        row = db.execute(text("""
            SELECT business_date, sessions, revenue, ad_spend
            FROM tw_summary_daily WHERE business_date = :today
        """), {"today": today}).mappings().first()
        print(f"    {dict(row) if row else '(no row)'}")

        print("\n  -- kpi_daily for 2026-04-09 through 2026-04-12 --")
        rows = db.execute(text("""
            SELECT business_date, sessions, orders, revenue, conversion_rate
            FROM kpi_daily
            WHERE business_date BETWEEN DATE '2026-04-09' AND DATE '2026-04-12'
            ORDER BY business_date
        """)).mappings().all()
        for r in rows:
            print(f"    {dict(r)}")

        print("\n  -- tw_summary_daily for 2026-04-09 through 2026-04-12 --")
        rows = db.execute(text("""
            SELECT business_date, sessions, revenue, ad_spend
            FROM tw_summary_daily
            WHERE business_date BETWEEN DATE '2026-04-09' AND DATE '2026-04-12'
            ORDER BY business_date
        """)).mappings().all()
        for r in rows:
            print(f"    {dict(r)}")
        if not rows:
            print("    (no rows — TW sync never fetched these days)")

        print("\n  -- shopify_orders_daily for 2026-04-09 through 2026-04-12 --")
        rows = db.execute(text("""
            SELECT business_date, orders, revenue
            FROM shopify_orders_daily
            WHERE business_date BETWEEN DATE '2026-04-09' AND DATE '2026-04-12'
            ORDER BY business_date
        """)).mappings().all()
        for r in rows:
            print(f"    {dict(r)}")

        # =====================================================================
        # 4. source sync runs summary
        # =====================================================================
        hr("4. source_sync_runs latest-per-source")
        rows = db.execute(text("""
            SELECT DISTINCT ON (source_name)
              source_name, status, started_at, finished_at, records_processed
            FROM source_sync_runs
            ORDER BY source_name, started_at DESC
        """)).mappings().all()
        now = datetime.now(timezone.utc)
        for r in rows:
            age_min = None
            if r['started_at']:
                age_min = int((now - r['started_at']).total_seconds() // 60)
            stale_flag = ""
            if age_min is None:
                stale_flag = " (never-run)"
            elif age_min > 60 * 24:
                stale_flag = f" (STALE: {age_min // 60}h)"
            elif age_min > 60 * 6:
                stale_flag = f" ({age_min // 60}h old)"
            print(f"  {r['source_name']:<28}  {r['status']:<10}  records={r['records_processed']:>8}  {stale_flag}")

        # Also show source_config.configured flags
        print("\n  -- source_config.configured flags --")
        rows = db.execute(text("""
            SELECT source_name, configured, enabled, sync_mode, last_success_at, last_error
            FROM source_config ORDER BY source_name
        """)).mappings().all()
        for r in rows:
            err_snippet = (r['last_error'] or '')[:80] if r['last_error'] else ''
            print(f"  {r['source_name']:<28}  configured={r['configured']:<5} enabled={r['enabled']:<5} mode={r['sync_mode']:<8} {err_snippet}")

        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
