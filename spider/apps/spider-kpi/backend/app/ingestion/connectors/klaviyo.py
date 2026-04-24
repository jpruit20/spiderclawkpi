"""Klaviyo ingest connector.

Agustin's native grill app writes user-level state to Klaviyo (device
ownership, firmware versions, "Opened App" / "First Cooking Session"
events, phone platform) on top of Shopify's own Placed Order events.
This connector mirrors that into ``klaviyo_profiles`` + ``klaviyo_events``
so the dashboard has:

* a per-email map of physical grill ownership (including the Giant
  Huntsman differentiator surfaced via Shopify line items)
* app DAU/MAU and install-version telemetry distinct from the Venom
  controller's AWS stream
* Beta Customers list membership for the Firmware Beta Program

Incremental. Profiles pull uses ``updated`` timestamp filter; events
use ``datetime``. First run of each scans back 30 days by default
(tunable). All writes are idempotent (``ON CONFLICT DO NOTHING`` on
the Klaviyo-side UUIDs).

Auth: Klaviyo private API key. Keep ``KLAVIYO_API_KEY`` out of git.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

import requests
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import KlaviyoEvent, KlaviyoProfile
from app.services.source_health import finish_sync_run, start_sync_run, upsert_source_config


settings = get_settings()
logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    logger.addHandler(h)


BASE_URL = "https://a.klaviyo.com/api"
TIMEOUT = 30
# The Klaviyo REST API returns 10 per page by default on profiles/events.
# We raise to the max (100 for profiles, 200 for events) so a single
# sync cycle drains more efficiently.
PROFILE_PAGE_SIZE = 100
EVENT_PAGE_SIZE = 200
# First-run lookback for profiles + events when no prior sync_run exists.
DEFAULT_BACKFILL_DAYS = 30
# Safety cap so a wedged sync can't chew CPU forever. Each profile sync
# is ~1 HTTP call per 100 profiles; at 20k profiles that's 200 calls.
MAX_PAGES_PER_RUN = 500


class KlaviyoAuthError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    key = settings.klaviyo_api_key
    if not key:
        raise KlaviyoAuthError(
            "KLAVIYO_API_KEY is not set. Generate a private API key with read scopes "
            "for Profiles, Events, Metrics, and Lists at "
            "https://www.klaviyo.com/account#api-keys-tab, then set it on the droplet .env."
        )
    return {
        "Authorization": f"Klaviyo-API-Key {key}",
        "accept": "application/vnd.api+json",
        "revision": settings.klaviyo_api_revision,
    }


def _get(path: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """GET with rate-limit aware retries. Klaviyo returns 429 with a
    ``Retry-After`` header we honor."""
    url = f"{BASE_URL}{path}" if path.startswith("/") else path
    attempts = 0
    while True:
        attempts += 1
        try:
            resp = requests.get(url, headers=_headers(), params=params, timeout=TIMEOUT)
        except requests.RequestException as exc:
            if attempts >= 5:
                raise
            wait = min(2 ** attempts, 30)
            logger.warning("klaviyo: transport error %s, retrying in %ss", exc, wait)
            time.sleep(wait)
            continue

        if resp.status_code == 429 and attempts < 6:
            wait = int(resp.headers.get("Retry-After") or "5")
            logger.info("klaviyo: rate-limited, sleeping %ss (attempt %s)", wait, attempts)
            time.sleep(wait)
            continue
        if resp.status_code >= 500 and attempts < 5:
            wait = min(2 ** attempts, 30)
            logger.warning("klaviyo: %s, retrying in %ss", resp.status_code, wait)
            time.sleep(wait)
            continue
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Klaviyo API {resp.status_code} for {url}: {resp.text[:400]}"
            )
        return resp.json()


def _paginate(initial_path: str, initial_params: Optional[dict[str, Any]] = None) -> Iterable[dict[str, Any]]:
    """Yield raw JSON pages following the JSON:API ``links.next`` chain."""
    path_or_url: Optional[str] = initial_path
    params: Optional[dict[str, Any]] = initial_params
    page = 0
    while path_or_url:
        page += 1
        if page > MAX_PAGES_PER_RUN:
            logger.warning("klaviyo: page cap %s reached, stopping", MAX_PAGES_PER_RUN)
            return
        data = _get(path_or_url, params=params)
        yield data
        # After the first call, ``next`` is a full URL and params were
        # already baked in, so we clear them.
        path_or_url = (data.get("links") or {}).get("next")
        params = None


# ── Profile sync ─────────────────────────────────────────────────────

_PROFILE_FIELDS = (
    "email,phone_number,external_id,first_name,last_name,created,updated,"
    "last_event_date,properties"
)


def _flatten_profile(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a Klaviyo profile JSON:API resource into a dict of
    column values for the ``klaviyo_profiles`` table."""
    attrs = row.get("attributes") or {}
    props = attrs.get("properties") or {}

    device_types = props.get("deviceTypes") or []
    if isinstance(device_types, str):
        device_types = [device_types]
    device_firmwares = props.get("deviceFirmwareVersions") or []
    if isinstance(device_firmwares, str):
        device_firmwares = [device_firmwares]

    def _parse_dt(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    return {
        "klaviyo_id": row.get("id"),
        "external_id": attrs.get("externalId"),
        "email": attrs.get("email"),
        "phone_number": attrs.get("phoneNumber"),
        "first_name": attrs.get("firstName"),
        "last_name": attrs.get("lastName"),
        "device_types": [str(v) for v in device_types if v is not None],
        "device_firmware_versions": [str(v) for v in device_firmwares if v is not None],
        "product_ownership": props.get("Product Ownership"),
        "phone_os": props.get("phoneOS"),
        "phone_model": props.get("phoneModel"),
        "phone_os_version": props.get("phoneOSVersion"),
        "phone_brand": props.get("phoneBrand"),
        "app_version": props.get("appVersion"),
        "expected_next_order_date": props.get("Expected Date Of Next Order"),
        "raw_properties": props,
        "klaviyo_created_at": _parse_dt(attrs.get("created")),
        "klaviyo_updated_at": _parse_dt(attrs.get("updated")),
        "last_event_at": _parse_dt(attrs.get("lastEventDate")),
    }


def _latest_profile_updated(db: Session) -> Optional[datetime]:
    return db.execute(
        select(KlaviyoProfile.klaviyo_updated_at)
        .order_by(KlaviyoProfile.klaviyo_updated_at.desc().nullslast())
        .limit(1)
    ).scalar()


def _sync_profiles(db: Session, since: datetime) -> int:
    """Pull profiles updated since ``since``, upsert on klaviyo_id."""
    filter_expr = f"greater-than(updated,{since.strftime('%Y-%m-%dT%H:%M:%SZ')})"
    params = {
        "filter": filter_expr,
        "sort": "updated",
        "page[size]": PROFILE_PAGE_SIZE,
        "fields[profile]": _PROFILE_FIELDS,
    }
    inserted = 0
    updated = 0
    for page in _paginate("/profiles", params):
        rows = page.get("data") or []
        if not rows:
            break
        values = [_flatten_profile(r) for r in rows if r.get("id")]
        for v in values:
            stmt = pg_insert(KlaviyoProfile).values(**v)
            update_cols = {
                k: stmt.excluded[k]
                for k in v.keys()
                if k != "klaviyo_id"
            }
            stmt = stmt.on_conflict_do_update(
                index_elements=["klaviyo_id"],
                set_=update_cols,
            )
            result = db.execute(stmt)
            if result.rowcount:
                # `rowcount` is 1 for both INSERT and UPDATE via postgres
                # on-conflict; we track aggregate only.
                inserted += 1
        db.commit()
    logger.info("klaviyo profiles: %s upserted (since %s)", inserted, since.isoformat())
    return inserted


# ── Event sync ───────────────────────────────────────────────────────

_EVENT_FIELDS = "timestamp,event_properties,datetime,uuid"


def _latest_event_dt_for_metric(db: Session, metric_name: str) -> Optional[datetime]:
    return db.execute(
        select(KlaviyoEvent.event_datetime)
        .where(KlaviyoEvent.metric_name == metric_name)
        .order_by(KlaviyoEvent.event_datetime.desc())
        .limit(1)
    ).scalar()


def _metric_id_by_name(db: Session) -> dict[str, str]:
    """Resolve configured metric names to Klaviyo IDs. Cached per-call.

    The ``/metrics`` endpoint does not accept a ``page[size]`` filter
    (verified 2026-04-24 — it returns HTTP 400 "page_size is not a
    valid field for the resource 'metric'"). Default page size is
    small, so we follow the ``links.next`` cursor until the account's
    metric list is exhausted. Typical accounts have fewer than 100
    metrics, so this is 2-3 round trips.
    """
    out: dict[str, str] = {}
    path_or_url: Optional[str] = "/metrics"
    while path_or_url:
        page = _get(path_or_url)
        for row in page.get("data") or []:
            attrs = row.get("attributes") or {}
            name = attrs.get("name")
            if name:
                out[name] = row.get("id")
        path_or_url = (page.get("links") or {}).get("next")
    return out


def _flatten_event(row: dict[str, Any], metric_name: str, metric_id: str) -> dict[str, Any]:
    attrs = row.get("attributes") or {}
    rels = row.get("relationships") or {}
    profile_rel = ((rels.get("profile") or {}).get("data") or {})
    dt_str = attrs.get("datetime")
    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00")) if dt_str else None
    props = attrs.get("eventProperties") or {}
    # Profile email/external_id aren't on the event itself unless we
    # sideload the profile — we leave them empty here and fill them at
    # query time by joining to klaviyo_profiles on klaviyo_profile_id.
    return {
        "klaviyo_event_id": row.get("id"),
        "metric_id": metric_id,
        "metric_name": metric_name,
        "klaviyo_profile_id": profile_rel.get("id"),
        "email": None,
        "external_id": None,
        "event_datetime": dt,
        "properties": props,
    }


def _sync_events_for_metric(
    db: Session, metric_id: str, metric_name: str, since: datetime
) -> int:
    filter_expr = (
        f"and(equals(metric_id,\"{metric_id}\"),"
        f"greater-than(datetime,{since.strftime('%Y-%m-%dT%H:%M:%SZ')}))"
    )
    params = {
        "filter": filter_expr,
        "sort": "datetime",
        "page[size]": EVENT_PAGE_SIZE,
        "fields[event]": _EVENT_FIELDS,
    }
    inserted = 0
    for page in _paginate("/events", params):
        rows = page.get("data") or []
        if not rows:
            break
        values = [
            _flatten_event(r, metric_name, metric_id)
            for r in rows
            if r.get("id")
        ]
        for v in values:
            if v["event_datetime"] is None:
                continue
            stmt = pg_insert(KlaviyoEvent).values(**v).on_conflict_do_nothing(
                index_elements=["klaviyo_event_id"]
            )
            result = db.execute(stmt)
            if result.rowcount:
                inserted += 1
        db.commit()
    logger.info(
        "klaviyo events %r: %s new rows (since %s)", metric_name, inserted, since.isoformat()
    )
    return inserted


# ── Entry point ──────────────────────────────────────────────────────


def sync_klaviyo(db: Session) -> dict[str, Any]:
    """Hourly Klaviyo sweep: profiles then events for configured metrics.

    Returns a result dict compatible with ``_successful_result`` in the
    scheduler — ``{'ok': True, 'profiles': N, 'events': {...}}`` on
    success, ``{'ok': False, 'skipped': True}`` when the API key is
    missing (so the scheduler doesn't mark it as an error before
    credentials are provisioned).
    """
    if not settings.klaviyo_api_key:
        logger.info("klaviyo: KLAVIYO_API_KEY unset; skipping sync")
        upsert_source_config(
            db, "klaviyo",
            configured=False,
            config_json={"status": "awaiting_api_key"},
        )
        db.commit()
        return {"ok": False, "skipped": True, "reason": "no_api_key"}

    run = start_sync_run(db, "klaviyo", sync_type="poll")
    upsert_source_config(db, "klaviyo", configured=True)
    db.commit()
    total_events = 0
    events_by_metric: dict[str, int] = {}
    try:
        # --- Profiles ---
        since_profile = _latest_profile_updated(db) or (
            datetime.now(timezone.utc) - timedelta(days=DEFAULT_BACKFILL_DAYS)
        )
        profiles_n = _sync_profiles(db, since_profile)

        # --- Events ---
        try:
            metric_ids = _metric_id_by_name(db)
        except Exception:
            logger.exception("klaviyo: metric resolution failed")
            metric_ids = {}

        for metric_name in settings.klaviyo_event_metrics:
            metric_id = metric_ids.get(metric_name)
            if not metric_id:
                logger.warning("klaviyo: metric %r not found in account", metric_name)
                continue
            since_event = _latest_event_dt_for_metric(db, metric_name) or (
                datetime.now(timezone.utc) - timedelta(days=DEFAULT_BACKFILL_DAYS)
            )
            n = _sync_events_for_metric(db, metric_id, metric_name, since_event)
            events_by_metric[metric_name] = n
            total_events += n

        summary = {
            "ok": True,
            "profiles": profiles_n,
            "events": events_by_metric,
            "events_total": total_events,
        }
        run.metadata_json = {**(run.metadata_json or {}), "summary": summary}
        finish_sync_run(
            db, run,
            status="success",
            records_processed=profiles_n + total_events,
        )
        db.commit()
        return summary
    except Exception as exc:
        logger.exception("klaviyo sync failed")
        finish_sync_run(
            db, run,
            status="failed",
            error_message=str(exc)[:500],
        )
        db.commit()
        raise
