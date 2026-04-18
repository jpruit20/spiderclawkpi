#!/usr/bin/env python3
"""Full Triple Whale archive export — pre-renewal snapshot.

Pulls every metric TW has for Spider Grills, day-by-day, back to a
configurable start date. Stores the raw API response in
``tw_raw_payloads`` (upsert by business_date) so we own the full shape
forever, and optionally dumps a mirror archive to compressed JSONL on
disk for portability.

Why this exists (Joseph, 2026-04-18): TW annual renewal is coming up;
we may not renew. Before then, capture everything.

Metric discovery: starts from every metric ID already catalogued in
``tw_metric_catalog`` (689 at time of writing). If a new metric shows
up in a response, the connector's catalog-as-we-go logic adds it for
the next day's request. Requests are chunked because TW rate-limits
very large metric lists.

Safe to re-run. ``--skip-existing`` skips business_dates already in
``tw_raw_payloads`` whose response has at least one metric value —
lets you resume an interrupted archive without re-hitting the API.

Usage:
    # Default: last 3 years through today, skip already-captured days
    python scripts/tw_full_archive_export.py --skip-existing

    # Specific range
    python scripts/tw_full_archive_export.py --start 2022-01-01 --end 2024-12-31

    # Also mirror to disk
    python scripts/tw_full_archive_export.py --archive-dir /data/tw-archive

    # Smaller chunks if TW starts rejecting big metric lists
    python scripts/tw_full_archive_export.py --metrics-per-request 50
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


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

import requests  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.ingestion.connectors.triplewhale import (  # noqa: E402
    SUMMARY_URL,
    TIMEOUT_SECONDS,
    _apply_summary_fields,
    _build_metric_index,
    _normalize,
)
from app.models import (  # noqa: E402
    TWMetricCatalog,
    TWRawPayload,
    TWSummaryDaily,
    TWSummaryIntraday,
)


logger = logging.getLogger("tw_archive")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def _discover_metric_ids(db) -> list[str]:
    rows = db.execute(select(TWMetricCatalog.metric_id)).scalars().all()
    # Exclude any absurdly long or malformed IDs (defensive — TW
    # catalog is clean, but a corrupted response once planted a junk
    # ID that made the next request 413).
    return sorted({m for m in rows if isinstance(m, str) and 2 < len(m) < 200})


def _chunks(items: list[str], n: int) -> list[list[str]]:
    return [items[i : i + n] for i in range(0, len(items), n)]


def _deep_merge_response(into: dict[str, Any], new: Any) -> None:
    """Merge ``new`` response JSON into ``into`` in place.

    TW's summary-page response is a nested shape with metric objects
    scattered throughout. We flatten on metric_id and dedup, so multiple
    chunked requests produce one unified payload.
    """
    # Extract metric objects from both
    if not isinstance(into.get("_merged_metrics"), dict):
        into["_merged_metrics"] = {}
    metrics = into["_merged_metrics"]

    objects: list[dict[str, Any]] = []

    def _collect(n: Any) -> None:
        if isinstance(n, dict):
            if "id" in n and "values" in n and isinstance(n.get("values"), dict):
                objects.append(n)
            for v in n.values():
                _collect(v)
        elif isinstance(n, list):
            for it in n:
                _collect(it)

    _collect(new)
    for m in objects:
        mid = m.get("id")
        if isinstance(mid, str):
            metrics[mid] = m

    # Preserve response metadata from the first request that brought it
    for k, v in (new or {}).items() if isinstance(new, dict) else []:
        if k not in into and k != "_merged_metrics":
            into[k] = v


def _fetch_day(
    session: requests.Session,
    headers: dict[str, str],
    shop_domain: str,
    target_date: date,
    metric_ids: list[str],
    metrics_per_request: int,
    sleep_between_chunks: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fetch a single day, chunking the metric list if needed.

    Returns ``(merged_response, request_payload)`` — the request_payload
    holds the metadata (period, timezone, chunk count) so TWRawPayload
    can record provenance.
    """
    merged: dict[str, Any] = {}
    chunks = _chunks(metric_ids, metrics_per_request)

    for i, chunk in enumerate(chunks):
        payload = {
            "period": {"start": target_date.isoformat(), "end": target_date.isoformat()},
            "timezone": "America/New_York",
            "todayHour": 23,
            "shopDomain": shop_domain,
            "panel": "summary",
            "metrics": chunk,
        }
        try:
            resp = session.post(
                SUMMARY_URL, headers=headers, json=payload, timeout=TIMEOUT_SECONDS
            )
            resp.raise_for_status()
            body = resp.json()
            _deep_merge_response(merged, body)
        except Exception:
            logger.exception(
                "chunk %d/%d failed for %s (%d metrics)",
                i + 1,
                len(chunks),
                target_date,
                len(chunk),
            )
            # Continue — partial days still useful; log + move on.
        if i < len(chunks) - 1 and sleep_between_chunks > 0:
            time.sleep(sleep_between_chunks)

    request_summary = {
        "period": {"start": target_date.isoformat(), "end": target_date.isoformat()},
        "timezone": "America/New_York",
        "todayHour": 23,
        "shopDomain": shop_domain,
        "panel": "summary",
        "metrics_count": len(metric_ids),
        "chunks_sent": len(chunks),
        "archived_by": "tw_full_archive_export.py",
    }
    return merged, request_summary


def _dump_disk_archive(archive_dir: Path, target_date: date, merged: dict[str, Any]) -> None:
    year_dir = archive_dir / f"{target_date.year:04d}"
    year_dir.mkdir(parents=True, exist_ok=True)
    out = year_dir / f"{target_date.isoformat()}.json.gz"
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump(merged, f, separators=(",", ":"), default=str)


def _existing_business_dates(db) -> set[date]:
    rows = db.execute(
        select(TWRawPayload.business_date, TWRawPayload.response_payload)
    ).all()
    out: set[date] = set()
    for bd, payload in rows:
        if not bd:
            continue
        # Consider existing only if payload actually has metrics.
        idx = _build_metric_index(payload or {})
        if idx:
            out.add(bd)
    return out


def run(
    start: date,
    end: date,
    skip_existing: bool,
    archive_dir: Path | None,
    metrics_per_request: int,
    sleep_between_requests: float,
    sleep_between_chunks: float,
) -> int:
    settings = get_settings()
    if not (settings.triplewhale_api_key and settings.shopify_store_url):
        logger.error("TW API key or shop domain not configured — aborting")
        return 2

    headers = {
        "x-api-key": settings.triplewhale_api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    session = requests.Session()

    if archive_dir is not None:
        archive_dir.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as db:
        metric_ids = _discover_metric_ids(db)
        logger.info("discovered %d metric IDs from tw_metric_catalog", len(metric_ids))
        if not metric_ids:
            logger.error(
                "no catalogued metrics yet — run the normal TW sync at least once first"
            )
            return 2

        existing: set[date] = set()
        if skip_existing:
            existing = _existing_business_dates(db)
            logger.info("skip-existing: %d days already archived", len(existing))

        total_days = (end - start).days + 1
        logger.info(
            "archiving %d days from %s to %s (chunks of %d metrics/req)",
            total_days,
            start,
            end,
            metrics_per_request,
        )

        fetched = 0
        skipped = 0
        errors = 0
        cur = start
        while cur <= end:
            if skip_existing and cur in existing:
                skipped += 1
                cur += timedelta(days=1)
                continue

            try:
                merged, req_summary = _fetch_day(
                    session,
                    headers,
                    settings.shopify_store_url,
                    cur,
                    metric_ids,
                    metrics_per_request,
                    sleep_between_chunks,
                )

                raw = db.execute(
                    select(TWRawPayload).where(TWRawPayload.business_date == cur)
                ).scalars().first()
                if raw is None:
                    raw = TWRawPayload(business_date=cur)
                    db.add(raw)
                raw.request_payload = req_summary
                raw.response_payload = merged

                # Also refresh the summary daily row with the richer
                # data — lets the Marketing page benefit immediately.
                normalized = _normalize(merged, {"period": req_summary["period"]})
                daily = db.execute(
                    select(TWSummaryDaily).where(TWSummaryDaily.business_date == cur)
                ).scalars().first()
                if daily is None:
                    daily = TWSummaryDaily(business_date=cur)
                    db.add(daily)
                _apply_summary_fields(daily, normalized)

                intra_bucket = datetime.combine(
                    cur, datetime.min.time(), tzinfo=timezone.utc
                )
                intra = db.execute(
                    select(TWSummaryIntraday).where(
                        TWSummaryIntraday.bucket_start == intra_bucket
                    )
                ).scalars().first()
                if intra is not None:
                    _apply_summary_fields(intra, normalized)

                if archive_dir is not None:
                    _dump_disk_archive(archive_dir, cur, merged)

                fetched += 1
                if fetched % 10 == 0:
                    db.commit()
                    logger.info(
                        "  committed through %s (fetched=%d skipped=%d errors=%d)",
                        cur,
                        fetched,
                        skipped,
                        errors,
                    )
            except Exception:
                errors += 1
                logger.exception("failed on %s", cur)

            cur += timedelta(days=1)
            if sleep_between_requests > 0:
                time.sleep(sleep_between_requests)

        db.commit()

    logger.info(
        "done: fetched=%d skipped=%d errors=%d",
        fetched,
        skipped,
        errors,
    )
    return 0 if errors == 0 else 1


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> int:
    today = date.today()
    default_start = today.replace(year=today.year - 3)

    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=_parse_date, default=default_start,
                    help="start date YYYY-MM-DD (default: 3 years ago)")
    ap.add_argument("--end", type=_parse_date, default=today,
                    help="end date YYYY-MM-DD (default: today)")
    ap.add_argument("--skip-existing", action="store_true",
                    help="skip business_dates that already have a populated raw payload")
    ap.add_argument("--archive-dir", type=Path, default=None,
                    help="also dump compressed JSONL archive to this directory")
    ap.add_argument("--metrics-per-request", type=int, default=100,
                    help="chunk size for metrics list (default 100)")
    ap.add_argument("--sleep-between-requests", type=float, default=1.0,
                    help="seconds to sleep between days (default 1.0)")
    ap.add_argument("--sleep-between-chunks", type=float, default=0.3,
                    help="seconds to sleep between metric chunks within a day (default 0.3)")
    args = ap.parse_args()

    if args.end < args.start:
        logger.error("--end (%s) must be >= --start (%s)", args.end, args.start)
        return 2

    return run(
        start=args.start,
        end=args.end,
        skip_existing=args.skip_existing,
        archive_dir=args.archive_dir,
        metrics_per_request=args.metrics_per_request,
        sleep_between_requests=args.sleep_between_requests,
        sleep_between_chunks=args.sleep_between_chunks,
    )


if __name__ == "__main__":
    raise SystemExit(main())
