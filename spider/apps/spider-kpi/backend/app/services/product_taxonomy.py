"""Map raw AWS device ``grill_type`` strings to a human product family.

As of 2026-04-22 the fleet has three visible product lines (four including
Unknown), and *firmware history* — not just the latest-reported firmware
on the device shadow — is what tells us which JOEHY V1 controllers are
Huntsman vs Weber Kettle.

## Hardware generations + firmware bands

* **V1 (JOEHY, ``W:K:22:1:V``)** — firmware ``0.0.x`` through ``01.01.35``.
  The AWS ``grill_type`` is always ``W:K:22:1:V`` on this hardware, so it
  is useless for distinguishing Huntsman from Weber Kettle; we have to
  look at which firmware flavour the factory flashed:
    * Factory-flashed ``01.01.33`` → Huntsman (ships with the 0-700°F
      range enabled at build time).
    * Factory-flashed ``01.01.34`` (and later) → Weber Kettle (ships
      with ``highTemp_enable=false``; flag can be flipped OTA to enable
      700°F mode on-device, but the hardware is still the Weber Kettle).
  **The catch:** Huntsman units factory-flashed on ``01.01.33`` get OTA'd
  up to newer V1 firmware once Joehy ships a point release. Once they're
  on ``01.01.34+``, the latest-observed firmware no longer tells us the
  grill family. We therefore look at the full *firmware history* for each
  device (from ``telemetry_sessions``): **if a device has EVER reported
  running 01.01.33, it is Huntsman hardware forever.** The opposite
  direction (a Weber Kettle that got rolled back to 01.01.33) has never
  happened in the field — that firmware won't run on a Weber Kettle
  because the screw-terminal count / fan drive differs.

* **V2 (ADN)** — firmware ``01.01.64`` through ``01.01.99`` (current
  alpha band is 01.01.90-99). V2 firmware reports ``grill_type`` as
  ``Huntsman``, ``Kettle``, or legacy ``Kettle22`` directly. The same
  ADN firmware binary covers Kettle 22, Kettle 26, and Webcraft, all
  rolled up to "Weber Kettle" here.

* **Giant Huntsman** — distinct SKU, not distinguishable from regular
  Huntsman in AWS data today. Per Joseph 2026-04-22, until Agustín's
  app-integration signal lands, we consolidate Giant Huntsman into the
  single ``Huntsman`` bucket. The constant ``FAMILY_GIANT_HUNTSMAN``
  still exists so we can flip ``CONSOLIDATE_GIANT_HUNTSMAN = False``
  once the differentiator is available.

## Deprecated / never use

* ``kettle_22`` (lowercase, underscored) — legacy stream-event value
* ``C:G:XT:1:D`` — old dev-branch AWS model string

Both are treated as ``Unknown`` so bad data stays visible in the UI.

## Efficient batch classification

Every page that classifies a fleet needs two inputs per device: the
latest ``(grill_type, firmware_version)`` *and* the device's firmware
history (to catch OTA'd Huntsman units). To avoid N+1 queries, callers
should build one ``huntsman_device_ids`` set up front via
:func:`build_huntsman_device_ids`, then pass it to :func:`classify_product`
for every device in the batch:

    huntsman_device_ids = build_huntsman_device_ids(db)
    for device_id, grill_type, firmware in rows:
        family = classify_product(
            grill_type, firmware,
            device_id=device_id,
            huntsman_device_ids=huntsman_device_ids,
        )

The helper is TTL-cached (5 min, process-local) so per-request cost is
amortized to zero inside that window.
"""
from __future__ import annotations

import threading
import time as _time
from typing import Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


FAMILY_WEBER_KETTLE = "Weber Kettle"
FAMILY_HUNTSMAN = "Huntsman"
FAMILY_GIANT_HUNTSMAN = "Giant Huntsman"
FAMILY_UNKNOWN = "Unknown"

# Families surfaced in rollups. While CONSOLIDATE_GIANT_HUNTSMAN is True,
# Giant Huntsman will always roll into Huntsman and the bucket will read
# zero — we keep it in ALL_FAMILIES so existing UI code that hard-codes
# the label doesn't break, but the count will be 0 until we flip the
# consolidation flag.
ALL_FAMILIES = (FAMILY_WEBER_KETTLE, FAMILY_HUNTSMAN, FAMILY_GIANT_HUNTSMAN, FAMILY_UNKNOWN)

# Families that actually receive classification under the current
# consolidation policy. When CONSOLIDATE_GIANT_HUNTSMAN=True, Giant
# Huntsman is not returned — callers that iterate over *only* the
# currently-classified families should use ACTIVE_FAMILIES instead.
CONSOLIDATE_GIANT_HUNTSMAN = True
ACTIVE_FAMILIES = (
    (FAMILY_WEBER_KETTLE, FAMILY_HUNTSMAN, FAMILY_UNKNOWN)
    if CONSOLIDATE_GIANT_HUNTSMAN
    else (FAMILY_WEBER_KETTLE, FAMILY_HUNTSMAN, FAMILY_GIANT_HUNTSMAN, FAMILY_UNKNOWN)
)

# Deprecated AWS grill_type tokens — should not appear on any current
# device. Surface them as Unknown so bad data is visible.
DEPRECATED_GRILL_TYPES = frozenset({"kettle_22", "C:G:XT:1:D"})

# JOEHY's single AWS model — used for both Huntsman and Weber Kettle,
# distinguished only by which firmware the factory flashed.
JOEHY_MODEL = "W:K:22:1:V"

# JOEHY V1 firmware versions that indicate a Huntsman factory flash.
# Today this is just 01.01.33 — the sole V1 release that ships with the
# 0-700°F range enabled at build time. Kept as a frozenset so future
# Huntsman-only V1 point releases can be added without touching logic.
JOEHY_HUNTSMAN_FIRMWARE = frozenset({"01.01.33"})


def _norm_fw(fw: Optional[str]) -> str:
    """Firmware strings arrive in several shapes (``'vers: "01.01.33"'``,
    ``'01.01.33'``, ``' 01.01.33 '``, ``'"01.01.33"'``). Strip them down
    to the bare version number for comparison."""
    if fw is None:
        return ""
    raw = str(fw).strip()
    # Drop a ``vers:`` / ``Vers:`` / ``version=`` prefix if present
    for prefix in ("vers:", "Vers:", "VERS:", "version="):
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()
            break
    # Strip surrounding quotes (ASCII and curly)
    for q in ('"', "'", "\u201c", "\u201d", "\u2018", "\u2019"):
        raw = raw.replace(q, "")
    return raw.strip()


def _is_huntsman_firmware(fw: Optional[str]) -> bool:
    """True if this firmware-version string indicates the Huntsman
    factory flash on V1 JOEHY hardware."""
    return _norm_fw(fw) in JOEHY_HUNTSMAN_FIRMWARE


def classify_product(
    grill_type: Optional[str],
    firmware_version: Optional[str] = None,
    *,
    device_id: Optional[str] = None,
    huntsman_device_ids: Optional[set[str]] = None,
) -> str:
    """Return the product family label for a device.

    Args:
        grill_type: The raw ``grill_type`` from AWS (``W:K:22:1:V`` for
            V1 JOEHY; ``Huntsman`` / ``Kettle`` / ``Kettle22`` for V2
            ADN; deprecated tokens collapse to Unknown).
        firmware_version: The latest-observed firmware version for the
            device. Only consulted when the hardware is V1 JOEHY (where
            firmware carries the Huntsman-vs-Kettle distinction).
        device_id: Optional device identifier. When provided along with
            ``huntsman_device_ids``, we use the full firmware history
            for the device to catch Huntsman units that OTA'd past
            01.01.33 and would otherwise look like Weber Kettle in the
            latest-only view.
        huntsman_device_ids: The set of device_ids that have ever
            reported running a Huntsman firmware. Build via
            :func:`build_huntsman_device_ids` and pass to every call
            in a batch.

    Case-insensitive on the family names ("kettle" == "Kettle"), but
    preserves the exact ``W:K:22:1:V`` match for the JOEHY path.
    """
    if not grill_type:
        return FAMILY_UNKNOWN

    raw = str(grill_type).strip()
    if raw in DEPRECATED_GRILL_TYPES:
        return FAMILY_UNKNOWN

    low = raw.lower()

    # ── V2 ADN hardware — grill_type is authoritative ────────────────
    if low == "huntsman":
        return FAMILY_HUNTSMAN
    if low in ("giant huntsman", "giant_huntsman"):
        return FAMILY_HUNTSMAN if CONSOLIDATE_GIANT_HUNTSMAN else FAMILY_GIANT_HUNTSMAN
    if low in ("kettle", "kettle22"):
        return FAMILY_WEBER_KETTLE

    # ── V1 JOEHY hardware — firmware history tells the story ─────────
    if raw == JOEHY_MODEL:
        # 1. Prefer device history: if the device EVER ran Huntsman
        #    firmware, it's Huntsman hardware even if it's since
        #    been OTA'd to a later V1 release.
        if device_id and huntsman_device_ids is not None and device_id in huntsman_device_ids:
            return FAMILY_HUNTSMAN
        # 2. Fall back to current firmware — handles the case where
        #    history wasn't passed in (single-device endpoint) or the
        #    device is currently still on 01.01.33.
        if _is_huntsman_firmware(firmware_version):
            return FAMILY_HUNTSMAN
        return FAMILY_WEBER_KETTLE

    return FAMILY_UNKNOWN


# ── Huntsman-history helper (cached) ─────────────────────────────────
#
# Scans telemetry_sessions for every device_id that has EVER reported
# running a Huntsman V1 firmware. Callers pass the resulting set into
# classify_product for batch classification. Cached for 5 min so the
# heavy scan runs once per request cycle at most.

_HUNTSMAN_CACHE_TTL_SECONDS = 300
_huntsman_cache: tuple[float, frozenset[str]] | None = None
_huntsman_cache_lock = threading.Lock()


def build_huntsman_device_ids(db: Session, *, force: bool = False) -> set[str]:
    """Return the set of device_ids that have ever reported running a
    Huntsman-flavour firmware (per ``JOEHY_HUNTSMAN_FIRMWARE``).

    Sources: both ``telemetry_sessions`` *and* ``telemetry_stream_events``.
    Sessions is authoritative for most devices, but a device that has
    stream activity but hasn't rolled up into a session yet (fresh boot,
    or stream lag during the 2026-04-09+ session-staleness window) would
    be missed by sessions alone.

    5-minute TTL in-memory cache — per-process, fine for the 1-2 app
    worker setup. Flip ``force=True`` to refresh immediately (used by
    ops endpoints that want a current read).
    """
    global _huntsman_cache
    now = _time.time()
    if not force:
        with _huntsman_cache_lock:
            if _huntsman_cache is not None:
                ts, payload = _huntsman_cache
                if now - ts < _HUNTSMAN_CACHE_TTL_SECONDS:
                    return set(payload)

    # Two-source union. Both queries are cheap: on sessions we group by
    # (device_id, firmware_version) which hits the existing idx, and on
    # stream events we restrict to the narrow firmware-version set.
    fw_list = sorted(JOEHY_HUNTSMAN_FIRMWARE)
    huntsman_ids: set[str] = set()

    session_rows = db.execute(text("""
        SELECT DISTINCT device_id
        FROM telemetry_sessions
        WHERE device_id IS NOT NULL
          AND device_id NOT LIKE 'mac:%%'
          AND firmware_version = ANY(:fw_list)
    """), {"fw_list": fw_list}).all()
    for (did,) in session_rows:
        if did:
            huntsman_ids.add(did)

    # Also sweep the stream-event table — catches devices that never
    # produced a session but DID phone home on 01.01.33.
    try:
        stream_rows = db.execute(text("""
            SELECT DISTINCT device_id
            FROM telemetry_stream_events
            WHERE device_id IS NOT NULL
              AND firmware_version = ANY(:fw_list)
        """), {"fw_list": fw_list}).all()
        for (did,) in stream_rows:
            if did:
                huntsman_ids.add(did)
    except Exception:
        # Stream-event table may not exist in every environment
        # (minimal test DBs). Session data alone is acceptable.
        pass

    with _huntsman_cache_lock:
        _huntsman_cache = (now, frozenset(huntsman_ids))
    return huntsman_ids


def classify_shopify_line_item(title: Optional[str]) -> str:
    """Map a Shopify line-item title to a product family for rollups.

    Keeps the same Giant-Huntsman-consolidation behaviour as
    :func:`classify_product` so fleet.py's Shopify counter doesn't
    disagree with the telemetry-based counter.
    """
    if not title:
        return FAMILY_UNKNOWN
    low = title.lower()
    if "giant" in low and "huntsman" in low:
        return FAMILY_HUNTSMAN if CONSOLIDATE_GIANT_HUNTSMAN else FAMILY_GIANT_HUNTSMAN
    if "huntsman" in low:
        return FAMILY_HUNTSMAN
    if "venom" in low or "kettle" in low or "weber" in low:
        return FAMILY_WEBER_KETTLE
    return FAMILY_UNKNOWN
