"""Staleness watchdog: daily sanity-check that key data tables are fresh.

Runs shortly before the morning email (6:45am ET) so Joseph gets a
heads-up if any ingest pipeline has silently fallen behind. Mirrors
the gap that hit telemetry_history_daily when the materializer wasn't
scheduled — once it was caught, we installed the timer. This watchdog
catches the *next* time something similar happens.

Design:

* Each check reports a ``latest_at`` timestamp and a ``threshold`` —
  if the latest value is older than the threshold, the table is stale.
* Thresholds are intentionally generous (36-48h) on daily rollup
  tables so genuine one-day ingest hiccups don't page every morning.
* Returns the whole set (stale AND fresh) so callers can log/display
  the state, not just alert on failure.
* Fail-silent on individual checks — if one query errors, others run.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session


logger = logging.getLogger(__name__)
BUSINESS_TZ = ZoneInfo("America/New_York")


@dataclass
class CheckResult:
    table: str
    latest_at: Optional[datetime | date]
    threshold_hours: float
    age_hours: Optional[float]
    stale: bool
    notes: str = ""
    row_count: Optional[int] = None


def _age_hours(latest: Optional[datetime | date], now_utc: datetime) -> Optional[float]:
    if latest is None:
        return None
    if isinstance(latest, datetime):
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        return (now_utc - latest).total_seconds() / 3600.0
    # date: treat as end-of-day UTC — generous
    as_dt = datetime(latest.year, latest.month, latest.day, 23, 59, 59, tzinfo=timezone.utc)
    return (now_utc - as_dt).total_seconds() / 3600.0


def _check_daily(
    db: Session, table: str, date_col: str, threshold_hours: float, now_utc: datetime,
) -> CheckResult:
    try:
        latest = db.execute(text(f"SELECT MAX({date_col}) FROM {table}")).scalar()
        total = db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
    except Exception as exc:
        logger.warning("staleness: %s query failed: %s", table, exc)
        return CheckResult(table=table, latest_at=None, threshold_hours=threshold_hours,
                           age_hours=None, stale=True, notes=f"query_failed: {exc}")
    age = _age_hours(latest, now_utc)
    stale = (age is None) or (age > threshold_hours)
    return CheckResult(
        table=table, latest_at=latest, threshold_hours=threshold_hours,
        age_hours=age, stale=stale, row_count=int(total),
    )


def _check_intraday(
    db: Session, table: str, ts_col: str, threshold_hours: float, now_utc: datetime,
) -> CheckResult:
    try:
        latest = db.execute(text(f"SELECT MAX({ts_col}) FROM {table}")).scalar()
        total = db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
    except Exception as exc:
        logger.warning("staleness: %s query failed: %s", table, exc)
        return CheckResult(table=table, latest_at=None, threshold_hours=threshold_hours,
                           age_hours=None, stale=True, notes=f"query_failed: {exc}")
    age = _age_hours(latest, now_utc)
    stale = (age is None) or (age > threshold_hours)
    return CheckResult(
        table=table, latest_at=latest, threshold_hours=threshold_hours,
        age_hours=age, stale=stale, row_count=int(total),
    )


# Threshold rules:
#   daily rollups     → 36h  (yesterday should be rolled up by 4am today)
#   webhook-driven    → 12h  (event-driven sources, quiet periods are normal)
#   continuous streams → 1h   (telemetry firehose should never pause this long)
#   API-polled        → 3h   (freshdesk sync should stay under this)
#
# clickup_tasks + slack_messages are webhook-driven: a quiet Friday
# evening with no new tasks/messages is NOT a pipeline failure, it's
# reality. We only want to alert if something's structurally wrong.
CHECKS: list[tuple[str, str, str, float]] = [
    # (kind, table, column, threshold_hours)
    ("daily",    "telemetry_history_daily", "business_date",   36.0),
    ("daily",    "kpi_daily",               "business_date",   36.0),
    ("daily",    "freshdesk_tickets_daily", "business_date",   36.0),
    ("daily",    "clickup_tasks_daily",     "business_date",   36.0),
    ("daily",    "slack_activity_daily",    "business_date",   36.0),
    ("intraday", "telemetry_stream_events", "sample_timestamp", 1.0),
    ("intraday", "freshdesk_tickets",       "updated_at_source", 6.0),
    ("intraday", "clickup_tasks",           "date_updated",    12.0),
    ("intraday", "slack_messages",          "ts_dt",           12.0),
]


def run(db: Session) -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    results: list[CheckResult] = []
    for kind, table, col, threshold in CHECKS:
        fn = _check_daily if kind == "daily" else _check_intraday
        results.append(fn(db, table, col, threshold, now_utc))

    stale = [r for r in results if r.stale]
    return {
        "generated_at": now_utc.isoformat(),
        "checks_total": len(results),
        "stale_count": len(stale),
        "stale": [
            {
                "table": r.table,
                "latest_at": r.latest_at.isoformat() if r.latest_at else None,
                "age_hours": round(r.age_hours, 1) if r.age_hours is not None else None,
                "threshold_hours": r.threshold_hours,
                "row_count": r.row_count,
                "notes": r.notes,
            }
            for r in stale
        ],
        "all": [
            {
                "table": r.table,
                "latest_at": r.latest_at.isoformat() if r.latest_at else None,
                "age_hours": round(r.age_hours, 1) if r.age_hours is not None else None,
                "threshold_hours": r.threshold_hours,
                "row_count": r.row_count,
                "stale": r.stale,
                "notes": r.notes,
            }
            for r in results
        ],
    }


def format_slack_message(report: dict[str, Any]) -> str:
    stale = report.get("stale") or []
    if not stale:
        return ""
    lines = [":warning: *Spider KPI data staleness alert*\n"]
    for s in stale:
        age = s.get("age_hours")
        latest = s.get("latest_at") or "(empty)"
        age_str = f"{age:.1f}h" if age is not None else "N/A"
        threshold = s.get("threshold_hours")
        lines.append(f"• `{s['table']}` — latest: {latest} (age {age_str} > threshold {threshold}h)")
    lines.append(
        "\nCheck the responsible job: morning-email pipeline, materializer, "
        "shopify/freshdesk/clickup/slack sync. `systemctl list-timers` on the droplet."
    )
    return "\n".join(lines)
