"""First-boot webhook emitter for Shelob.

When a MAC's first-ever telemetry event lands in
telemetry_stream_events, POST to Shelob's /api/devices/first-boot so
Shelob can materialize the bound persona onto the device shadow.

Detection pattern:
- In-process cache of MACs we've already evaluated (so we don't query
  per insert in steady state).
- On first sight per process, query telemetry_stream_events for any
  prior rows with this MAC. >1 row total = not a first boot (process
  restart memory loss is fine — we'd just incur one no-op DB check
  per MAC).
- Fire the webhook only when the count is exactly 1 (the row we just
  inserted).

Best-effort: webhook failures are logged + swallowed. Telemetry
ingestion never blocks on Shelob being reachable.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings


log = logging.getLogger("kpi.streaming.shelob_webhook")
settings = get_settings()

# Process-local cache of MACs we've evaluated. Lock to keep it sane
# across the threadpool FastAPI uses for sync handlers.
_seen_macs: set[str] = set()
_seen_lock = threading.Lock()


def _is_configured() -> bool:
    return bool(settings.shelob_first_boot_url and settings.shelob_webhook_token)


def _extract_macs(records: list[dict[str, Any]]) -> set[str]:
    macs: set[str] = set()
    for r in records:
        raw = r.get("raw_payload") or {}
        reported = (raw.get("device_data") or {}).get("reported") or {}
        mac = reported.get("mac")
        if isinstance(mac, str):
            normalized = "".join(c for c in mac.lower() if c.isalnum())
            if len(normalized) == 12:
                macs.add(normalized)
    return macs


def _is_brand_new(db: Session, mac: str) -> bool:
    """Returns True if the MAC has at most 1 row in
    telemetry_stream_events (i.e. only the row we just inserted)."""
    q = db.execute(
        text(
            "SELECT 1 FROM telemetry_stream_events "
            "WHERE raw_payload->'device_data'->'reported'->>'mac' = :mac "
            "LIMIT 2"
        ),
        {"mac": mac},
    )
    return len(list(q.fetchall())) <= 1


def _post(mac: str) -> None:
    try:
        resp = httpx.post(
            settings.shelob_first_boot_url,
            json={"mac": mac},
            headers={"X-Shelob-Webhook-Token": settings.shelob_webhook_token},
            timeout=5.0,
        )
        if resp.status_code >= 400:
            log.warning("shelob first-boot webhook %s for %s: %s", resp.status_code, mac, resp.text[:200])
        else:
            log.info("shelob first-boot webhook OK for %s", mac)
    except httpx.HTTPError as e:
        log.warning("shelob first-boot webhook http failure for %s: %s", mac, e)


def maybe_fire_first_boot(db: Session, normalized_records: list[dict[str, Any]]) -> None:
    """Call after write_stream_records. Cheap when the MACs in the
    batch are already in our seen-cache; otherwise does one DB count
    + (at most) one webhook call per truly-new MAC."""
    if not _is_configured():
        return
    candidates = _extract_macs(normalized_records)
    if not candidates:
        return

    fresh: set[str] = set()
    with _seen_lock:
        for mac in candidates:
            if mac not in _seen_macs:
                fresh.add(mac)
                _seen_macs.add(mac)

    for mac in fresh:
        try:
            if _is_brand_new(db, mac):
                _post(mac)
        except Exception as e:  # noqa: BLE001 — best-effort; never fail ingestion
            log.warning("first-boot evaluation failed for %s: %s", mac, e)
