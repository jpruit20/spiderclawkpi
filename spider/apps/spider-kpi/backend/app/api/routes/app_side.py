"""App-side fleet telemetry endpoint.

Serves the ``/api/telemetry/app-side`` payload that the Product Engineering
dashboard uses to visualize metrics derived from the Spider Grills mobile app
(React Native, ``com.spidergrillsapp``) — distinct from the device-side
DynamoDB/S3 telemetry pipeline.

The response *always* carries data split by source (``freshdesk`` vs
``app_backend``) *and* a source-agnostic ``combined`` rollup deduplicated by
MAC (for devices) and user_key (for users), so that once a direct backend
sync is added we can read both without double-counting shared users.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_dashboard_session
from app.models import (
    AppSideDaily,
    AppSideDeviceObservation,
    AppSideUserObservation,
)


router = APIRouter(prefix="/api", tags=["app_side"], dependencies=[Depends(require_dashboard_session)])
BUSINESS_TZ = ZoneInfo("America/New_York")

SOURCE_FRESHDESK = "freshdesk"
SOURCE_APP_BACKEND = "app_backend"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _sum_counters(dicts: list[dict[str, int]]) -> dict[str, int]:
    total: Counter[str] = Counter()
    for d in dicts:
        if not d:
            continue
        for k, v in d.items():
            total[str(k)] += int(v or 0)
    return dict(total.most_common())


def _top_n(dist: dict[str, int], n: int) -> list[dict[str, Any]]:
    total = sum(dist.values()) or 1
    return [
        {"value": k, "count": v, "pct": v / total}
        for k, v in sorted(dist.items(), key=lambda kv: kv[1], reverse=True)[:n]
    ]


@router.get("/telemetry/app-side")
def app_side_fleet(
    days: int = 90,
    start: str | None = None,
    end: str | None = None,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    days = max(1, min(days, 730))
    today_local = datetime.now(BUSINESS_TZ).date()
    end_date = _parse_date(end) or today_local
    start_date = _parse_date(start) or (end_date - timedelta(days=days - 1))
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    daily_rows = db.execute(
        select(AppSideDaily)
        .where(AppSideDaily.business_date >= start_date, AppSideDaily.business_date <= end_date)
        .order_by(AppSideDaily.business_date, AppSideDaily.source)
    ).scalars().all()

    # Split rows by source and build per-source aggregates.
    per_source_daily: dict[str, list[AppSideDaily]] = defaultdict(list)
    for row in daily_rows:
        per_source_daily[row.source].append(row)

    def aggregate_source(rows: list[AppSideDaily]) -> dict[str, Any]:
        app_versions = _sum_counters([r.app_version_dist for r in rows])
        firmwares = _sum_counters([r.firmware_version_dist for r in rows])
        controllers = _sum_counters([r.controller_model_dist for r in rows])
        phone_os = _sum_counters([r.phone_os_dist for r in rows])
        phone_brand = _sum_counters([r.phone_brand_dist for r in rows])
        phone_model = _sum_counters([r.phone_model_dist for r in rows])
        return {
            "observations": sum(r.observations for r in rows),
            "daily": [
                {
                    "business_date": r.business_date.isoformat(),
                    "observations": r.observations,
                    "unique_users": r.unique_users,
                    "unique_devices": r.unique_devices,
                }
                for r in rows
            ],
            # From the per-day rollups we get a *sum* of unique counts, which
            # over-counts users/devices seen on multiple days. We recompute
            # window-level uniqueness below from the raw observation tables
            # for the combined view; for per-source headlines the per-day
            # rollup is a reasonable "observations" proxy.
            "app_version_top": _top_n(app_versions, 12),
            "firmware_version_top": _top_n(firmwares, 12),
            "controller_model_top": _top_n(controllers, 8),
            "phone_os_top": _top_n(phone_os, 6),
            "phone_brand_top": _top_n(phone_brand, 8),
            "phone_model_top": _top_n(phone_model, 12),
        }

    # --- Window-level unique counts (deduped across days) -------------------
    # Cheap at our volumes — pull once per source from the observation tables.
    user_rows = db.execute(
        select(AppSideUserObservation)
        .where(
            AppSideUserObservation.business_date >= start_date,
            AppSideUserObservation.business_date <= end_date,
        )
    ).scalars().all()
    device_rows = db.execute(
        select(AppSideDeviceObservation)
        .where(
            AppSideDeviceObservation.business_date >= start_date,
            AppSideDeviceObservation.business_date <= end_date,
        )
    ).scalars().all()

    users_by_source: dict[str, set[str]] = defaultdict(set)
    for u in user_rows:
        users_by_source[u.source].add(u.user_key)

    devices_by_source: dict[str, set[str]] = defaultdict(set)
    devices_no_mac_by_source: dict[str, int] = defaultdict(int)
    for d in device_rows:
        if d.mac_normalized:
            devices_by_source[d.source].add(d.mac_normalized)
        else:
            devices_no_mac_by_source[d.source] += 1

    all_users: set[str] = set()
    for s in users_by_source.values():
        all_users |= s
    all_devices: set[str] = set()
    for s in devices_by_source.values():
        all_devices |= s

    # Overlap between sources — directly shows the "same people show up in
    # both Freshdesk and the app backend" case we want to avoid double counting.
    source_names = list(users_by_source.keys() | devices_by_source.keys())
    overlap = {}
    if SOURCE_FRESHDESK in source_names and SOURCE_APP_BACKEND in source_names:
        overlap = {
            "users_in_both": len(users_by_source[SOURCE_FRESHDESK] & users_by_source[SOURCE_APP_BACKEND]),
            "devices_in_both": len(devices_by_source[SOURCE_FRESHDESK] & devices_by_source[SOURCE_APP_BACKEND]),
            "users_only_freshdesk": len(users_by_source[SOURCE_FRESHDESK] - users_by_source[SOURCE_APP_BACKEND]),
            "users_only_app_backend": len(users_by_source[SOURCE_APP_BACKEND] - users_by_source[SOURCE_FRESHDESK]),
        }

    # Per-source structure (even if empty — makes it explicit on the frontend
    # that app_backend has no data yet).
    sources_payload = {}
    for source_name in [SOURCE_FRESHDESK, SOURCE_APP_BACKEND]:
        rows = per_source_daily.get(source_name, [])
        agg = aggregate_source(rows) if rows else {
            "observations": 0, "daily": [],
            "app_version_top": [], "firmware_version_top": [], "controller_model_top": [],
            "phone_os_top": [], "phone_brand_top": [], "phone_model_top": [],
        }
        agg["unique_users_window"] = len(users_by_source.get(source_name, set()))
        agg["unique_devices_window"] = len(devices_by_source.get(source_name, set()))
        agg["device_observations_without_mac"] = devices_no_mac_by_source.get(source_name, 0)
        agg["connected"] = bool(rows) or source_name == SOURCE_FRESHDESK
        sources_payload[source_name] = agg

    # Combined/deduped view across sources.
    combined_app_versions = _sum_counters([r.app_version_dist for r in daily_rows])
    combined_firmwares = _sum_counters([r.firmware_version_dist for r in daily_rows])
    combined_controllers = _sum_counters([r.controller_model_dist for r in daily_rows])
    combined_phone_os = _sum_counters([r.phone_os_dist for r in daily_rows])
    combined_phone_brand = _sum_counters([r.phone_brand_dist for r in daily_rows])
    combined_phone_model = _sum_counters([r.phone_model_dist for r in daily_rows])

    combined_payload = {
        "unique_users_window": len(all_users),
        "unique_devices_window": len(all_devices),
        "app_version_top": _top_n(combined_app_versions, 12),
        "firmware_version_top": _top_n(combined_firmwares, 12),
        "controller_model_top": _top_n(combined_controllers, 8),
        "phone_os_top": _top_n(combined_phone_os, 6),
        "phone_brand_top": _top_n(combined_phone_brand, 8),
        "phone_model_top": _top_n(combined_phone_model, 12),
    }

    latest_observed = max(
        (row.observed_at for row in user_rows if row.observed_at),
        default=None,
    )

    return {
        "window": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "days": (end_date - start_date).days + 1,
        },
        "sources": sources_payload,
        "combined": combined_payload,
        "overlap": overlap,
        "latest_observed_at": latest_observed.isoformat() if latest_observed else None,
        "notes": {
            "freshdesk": (
                "Derived from [AUTOMATED] diagnostic tickets submitted from the Spider Grills app. "
                "Represents only users who triggered the in-app diagnostics flow, not the full app population."
            ),
            "app_backend": (
                "Materialized from Klaviyo events the Spider Grills app fires (Device Paired, "
                "Device Unpaired, Cook Completed). Each event becomes an app-side observation; "
                "the daily rollup gives the active-app population and every device that's been "
                "paired or used since the events started flowing on 2026-04-28. The 'app_backend' "
                "label is preserved for schema continuity — a future direct-DB pull would write "
                "to the same partition."
            ),
            "combined": (
                "Users deduped by sha256(email), devices deduped by normalized MAC across sources. "
                "Safe to read as a union without double-counting overlap."
            ),
        },
    }
