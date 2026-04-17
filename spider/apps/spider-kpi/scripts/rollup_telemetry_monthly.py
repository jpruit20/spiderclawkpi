#!/usr/bin/env python3
"""Roll up telemetry_history_daily into telemetry_history_monthly.

Idempotent upsert on month_start.

The existing monthly table has a sparse column set; we stuff richer
per-month summary data (sessions, success rate, error rate, cook-style
mix, top firmware, top models, event totals, daily-average active
devices) into metadata_json so the dashboard and AI can query it
without repeatedly aggregating the daily table.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path


ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def _load_env(p: Path) -> None:
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
            v = v[1:-1]
        os.environ.setdefault(k.strip(), v)


_load_env(ENV_PATH)
BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import text  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


UPSERT_SQL = """
INSERT INTO telemetry_history_monthly (
    month_start, distinct_devices, distinct_engaged_devices, observed_mac_count,
    source, coverage_window_days, metadata_json, created_at, updated_at
) VALUES (
    :month_start, :distinct_devices, :distinct_engaged_devices, :observed_mac_count,
    :source, :coverage_window_days, CAST(:metadata_json AS JSONB), NOW(), NOW()
)
ON CONFLICT (month_start) DO UPDATE SET
    distinct_devices         = EXCLUDED.distinct_devices,
    distinct_engaged_devices = EXCLUDED.distinct_engaged_devices,
    observed_mac_count       = EXCLUDED.observed_mac_count,
    source                   = EXCLUDED.source,
    coverage_window_days     = EXCLUDED.coverage_window_days,
    metadata_json            = EXCLUDED.metadata_json,
    updated_at               = NOW()
"""


def main() -> int:
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT business_date, active_devices, engaged_devices, total_events, avg_rssi,
                   error_events, firmware_distribution, model_distribution, avg_cook_temp,
                   peak_hour_distribution, session_count, successful_sessions,
                   cook_styles_json, temp_range_json, duration_range_json, unique_devices_seen
              FROM telemetry_history_daily
             ORDER BY business_date
        """)).mappings().all()

        by_month: dict[date, list[dict]] = defaultdict(list)
        for r in rows:
            m = r["business_date"].replace(day=1)
            by_month[m].append(dict(r))

        upsert_rows: list[dict] = []
        for month_start, day_rows in sorted(by_month.items()):
            fw_total: Counter = Counter()
            model_total: Counter = Counter()
            hour_total: Counter = Counter()
            cook_styles: Counter = Counter()
            temp_ranges: Counter = Counter()
            duration_ranges: Counter = Counter()
            active_sum = engaged_sum = events_sum = errors_sum = 0
            sessions_sum = successful_sum = 0
            rssi_vals = []
            cook_temp_vals = []
            max_daily_active = 0
            for d in day_rows:
                active_sum += d["active_devices"] or 0
                engaged_sum += d["engaged_devices"] or 0
                events_sum += d["total_events"] or 0
                errors_sum += d["error_events"] or 0
                sessions_sum += d["session_count"] or 0
                successful_sum += d["successful_sessions"] or 0
                max_daily_active = max(max_daily_active, d["active_devices"] or 0)
                if d["avg_rssi"] is not None: rssi_vals.append(float(d["avg_rssi"]))
                if d["avg_cook_temp"] is not None: cook_temp_vals.append(float(d["avg_cook_temp"]))
                for k, v in (d.get("firmware_distribution") or {}).items(): fw_total[k] += int(v or 0)
                for k, v in (d.get("model_distribution") or {}).items(): model_total[k] += int(v or 0)
                for k, v in (d.get("peak_hour_distribution") or {}).items(): hour_total[str(k)] += int(v or 0)
                for k, v in (d.get("cook_styles_json") or {}).items(): cook_styles[k] += int(v or 0)
                for k, v in (d.get("temp_range_json") or {}).items(): temp_ranges[k] += int(v or 0)
                for k, v in (d.get("duration_range_json") or {}).items(): duration_ranges[k] += int(v or 0)

            n = len(day_rows)
            metadata = {
                "days_covered": n,
                "avg_daily_active_devices": round(active_sum / n, 1),
                "avg_daily_engaged_devices": round(engaged_sum / n, 1),
                "peak_daily_active_devices": max_daily_active,
                "total_events": events_sum,
                "total_error_events": errors_sum,
                "overall_error_rate": round(errors_sum / events_sum, 4) if events_sum else None,
                "total_sessions": sessions_sum,
                "total_successful_sessions": successful_sum,
                "overall_cook_success_rate": round(successful_sum / sessions_sum, 4) if sessions_sum else None,
                "avg_rssi": round(sum(rssi_vals) / len(rssi_vals), 2) if rssi_vals else None,
                "avg_cook_temp": round(sum(cook_temp_vals) / len(cook_temp_vals), 2) if cook_temp_vals else None,
                "firmware_top8": dict(fw_total.most_common(8)),
                "model_distribution": dict(model_total.most_common(10)),
                "peak_hours_top6": dict(sorted(hour_total.most_common(6), key=lambda kv: int(kv[0]))),
                "cook_styles": dict(cook_styles),
                "temp_ranges": dict(temp_ranges),
                "duration_ranges": dict(duration_ranges),
                "sources_used": sorted({(d.get("source") or "") for d in day_rows}) if any("source" in d for d in day_rows) else None,
            }

            upsert_rows.append({
                "month_start": month_start,
                "distinct_devices": max_daily_active,  # best-available proxy without stored device-set
                "distinct_engaged_devices": max(d["engaged_devices"] or 0 for d in day_rows),
                "observed_mac_count": max(d.get("unique_devices_seen") or d["active_devices"] or 0 for d in day_rows),
                "source": "rollup_from_daily",
                "coverage_window_days": n,
                "metadata_json": json.dumps(metadata),
            })

        for r in upsert_rows:
            db.execute(text(UPSERT_SQL), r)
        db.commit()
        print(f"Rolled up {len(upsert_rows)} months into telemetry_history_monthly.")
        for r in upsert_rows:
            m = json.loads(r["metadata_json"])
            print(f"  {r['month_start']} days={m['days_covered']} events={m['total_events']:>12,} sess={m['total_sessions']:>5} success={m['overall_cook_success_rate']}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
