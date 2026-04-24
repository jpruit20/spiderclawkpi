"""Map raw AWS device ``grill_type`` strings to a human product family.

As of 2026-04-22 the fleet has three visible product lines (four including
Unknown), and the *device shadow itself* carries the hardware signal we
need to distinguish Huntsman from Weber Kettle on V1 JOEHY controllers.

## Hardware generations + how we tell them apart

* **V1 (JOEHY, ``W:K:22:1:V``)** — firmware ``0.0.x`` through ``01.01.35``.
  The AWS ``grill_type`` is always ``W:K:22:1:V`` on this hardware, so it
  is useless for distinguishing Huntsman from Weber Kettle. We have two
  identifiers to fall back on, in strict priority order:

  1. **Shadow ``heat.t2.max``** — the factory-wired high-temp ceiling.
     Huntsman ships with ``max=700`` (0-700°F range enabled at build
     time). Weber Kettle ships with ``max=550``. This value is
     **stable across firmware OTAs** — a Huntsman that gets OTA'd from
     01.01.33 to 01.01.34 keeps ``max=700`` in its shadow. This is the
     authoritative V1 signal; fleet audit on 2026-04-22 confirmed
     100% separation across 1,820 active JOEHY devices (774 at 700,
     1,046 at 550, zero cross-contamination).
  2. **Firmware history** (fallback for devices with no shadow payload
     cached — e.g. ghost devices that have session history but no
     recent stream events). If a device has EVER reported running
     ``01.01.33``, treat it as Huntsman. The opposite direction (a
     Weber Kettle rolled back to 01.01.33) has never happened in the
     field — that firmware won't run on a Weber Kettle because the
     screw-terminal count / fan drive differs.
  3. **Current firmware** (last-ditch fallback for single-device
     endpoints where history isn't passed in). ``01.01.33`` → Huntsman,
     anything else → Weber Kettle. This is the weakest signal because
     it misses OTA'd Huntsman units.

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

# The factory-wired high-temp ceiling in the device shadow. This is the
# authoritative Huntsman-vs-Kettle signal on V1 JOEHY hardware and is
# stable across firmware OTAs. Values observed in the field (audit
# 2026-04-22): 700 → Huntsman (774 devs), 550 → Weber Kettle (1,046 devs),
# plus a handful of dev/miswired units at 287 / 371 which we treat as
# the default (Weber Kettle) because they lack the Huntsman factory flash.
T2_MAX_HUNTSMAN = 700
T2_MAX_WEBER_KETTLE = 550


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
    t2_max: Optional[int] = None,
) -> str:
    """Return the product family label for a device.

    Args:
        grill_type: The raw ``grill_type`` from AWS (``W:K:22:1:V`` for
            V1 JOEHY; ``Huntsman`` / ``Kettle`` / ``Kettle22`` for V2
            ADN; deprecated tokens collapse to Unknown).
        firmware_version: The latest-observed firmware version for the
            device. Weakest V1 signal; only consulted if ``t2_max`` and
            ``huntsman_device_ids`` are unavailable.
        device_id: Optional device identifier. When provided along with
            ``huntsman_device_ids``, we use the device's firmware
            history to catch Huntsman units whose shadow payload isn't
            in the current row set.
        huntsman_device_ids: The set of device_ids that have ever
            reported running a Huntsman firmware. Build via
            :func:`build_huntsman_device_ids` and pass to every call
            in a batch. Used as the secondary V1 signal (after
            ``t2_max``) so ghost devices with session history but no
            recent stream payloads still classify correctly.
        t2_max: The shadow ``heat.t2.max`` value (factory-wired
            high-temp ceiling). 700 → Huntsman, 550 → Weber Kettle.
            This is the authoritative V1 signal and is checked first —
            it is stable across firmware OTAs.

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

    # ── V1 JOEHY hardware — three-tier signal, strongest first ───────
    if raw == JOEHY_MODEL:
        # 1. AUTHORITATIVE: shadow heat.t2.max. 700 → Huntsman, 550 →
        #    Weber Kettle. Stable across OTAs (factory-wired hardware
        #    range). Caller is responsible for reading this off the
        #    latest raw_payload before calling us.
        if t2_max == T2_MAX_HUNTSMAN:
            return FAMILY_HUNTSMAN
        if t2_max == T2_MAX_WEBER_KETTLE:
            return FAMILY_WEBER_KETTLE
        # 2. Firmware history — catches ghost devices that haven't
        #    produced a recent raw_payload but did have a 01.01.33
        #    session in the past. Also catches OTA'd Huntsman units
        #    whose shadow wasn't passed in.
        if device_id and huntsman_device_ids is not None and device_id in huntsman_device_ids:
            return FAMILY_HUNTSMAN
        # 3. Weakest: current firmware alone. Misses OTA'd Huntsman, but
        #    useful for single-device endpoints where history wasn't
        #    precomputed.
        if _is_huntsman_firmware(firmware_version):
            return FAMILY_HUNTSMAN
        return FAMILY_WEBER_KETTLE

    return FAMILY_UNKNOWN


def extract_t2_max(raw_payload: Optional[dict]) -> Optional[int]:
    """Pull the shadow ``heat.t2.max`` value out of a raw_payload.

    Returns the integer max if present, otherwise None. Shape:
    ``raw_payload["device_data"]["reported"]["heat"]["t2"]["max"]``.

    Tolerates missing intermediate keys and non-dict values.
    """
    if not isinstance(raw_payload, dict):
        return None
    try:
        reported = (raw_payload.get("device_data") or {}).get("reported") or {}
        t2 = ((reported.get("heat") or {}).get("t2")) or {}
        v = t2.get("max")
        if v is None:
            return None
        return int(v)
    except (TypeError, ValueError, AttributeError):
        return None


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


# ── t2.max-by-device (cached) ────────────────────────────────────────
#
# The authoritative V1 discriminator lives in the shadow payload's
# ``heat.t2.max``. Reading it per-device in a loop would be
# O(devices) round-trips; one DISTINCT ON query pulls the whole
# fleet at once, then every callsite intersects against the batch.

_T2MAX_CACHE_TTL_SECONDS = 300
_t2max_cache: tuple[float, dict[str, int]] | None = None
_t2max_cache_lock = threading.Lock()


def build_t2_max_by_device(db: Session, *, force: bool = False) -> dict[str, int]:
    """Return ``{device_id: latest heat.t2.max}`` for every JOEHY device
    with a recent raw_payload.

    Pulled in a single DISTINCT ON pass over ``telemetry_stream_events``
    so the caller can classify the whole fleet without re-reading
    individual payloads. 5-minute TTL cache matches
    :func:`build_huntsman_device_ids`.

    Devices with no raw_payload (ghost devices) are absent from the
    returned dict; callers should fall through to firmware-history
    classification for those.
    """
    global _t2max_cache
    now = _time.time()
    if not force:
        with _t2max_cache_lock:
            if _t2max_cache is not None:
                ts, payload = _t2max_cache
                if now - ts < _T2MAX_CACHE_TTL_SECONDS:
                    return dict(payload)

    out: dict[str, int] = {}
    try:
        rows = db.execute(text("""
            SELECT DISTINCT ON (device_id)
                device_id,
                (raw_payload->'device_data'->'reported'->'heat'->'t2'->>'max')::int AS t2max
            FROM telemetry_stream_events
            WHERE grill_type = :gm
              AND raw_payload IS NOT NULL
              AND device_id IS NOT NULL
              AND device_id NOT LIKE 'mac:%%'
            ORDER BY device_id, sample_timestamp DESC
        """), {"gm": JOEHY_MODEL}).all()
        for did, v in rows:
            if did is not None and v is not None:
                try:
                    out[did] = int(v)
                except (TypeError, ValueError):
                    continue
    except Exception:
        # Stream-event table may not exist in every environment;
        # fall back to empty dict so callers drop to firmware history.
        pass

    with _t2max_cache_lock:
        _t2max_cache = (now, dict(out))
    return out


# ── Test-cohort exclusion (alpha / beta firmware testers) ────────────
#
# Devices enrolled in firmware alpha or beta programs skew every
# general-fleet metric — they're on experimental builds, their
# disconnect rates are noisy, their cook styles are dev-only. Fleet
# Health, product_distribution, firmware_distribution, and all other
# "how is the real fleet doing?" views exclude them by default.
# Firmware Hub is the only page that *wants* to see them and reads
# them directly from the cohort tables.
#
# Three overlapping sources of truth (we union all three):
#   1. BetaCohortMember rows in an active state
#   2. FirmwareDeployLog rows with cohort in (alpha, beta) that
#      reached the device (succeeded / in_flight / pending)
#   3. Any device currently reporting firmware matching ``01.01.9x``
#      — per Joseph 2026-04-22 that band is the active alpha

# Firmware versions in this band are considered alpha test builds.
# Regex matches normalized strings only — _norm_fw() should be applied
# first if the raw value might carry a ``vers:`` prefix or quotes.
import re as _re
ALPHA_FIRMWARE_REGEX = _re.compile(r"^01\.01\.9\d$")

_TEST_COHORT_CACHE_TTL_SECONDS = 300
_test_cohort_cache: tuple[float, frozenset[str]] | None = None
_test_cohort_cache_lock = threading.Lock()


def _is_alpha_firmware(fw: Optional[str]) -> bool:
    """True if this firmware-version string is in the 01.01.9x alpha band."""
    return bool(ALPHA_FIRMWARE_REGEX.match(_norm_fw(fw)))


def build_test_cohort_device_ids(db: Session, *, force: bool = False) -> set[str]:
    """Return the set of device_ids currently participating in firmware
    alpha or beta testing.

    General-fleet views exclude these. Firmware Hub + beta-program
    pages read them directly and are unaffected.

    Three sources unioned: ``BetaCohortMember`` (active states),
    ``FirmwareDeployLog`` with cohort in (alpha/beta) in an in-flight
    or succeeded state, and any device whose latest observed firmware
    matches the alpha band (``01.01.9x``).
    """
    global _test_cohort_cache
    now = _time.time()
    if not force:
        with _test_cohort_cache_lock:
            if _test_cohort_cache is not None:
                ts, payload = _test_cohort_cache
                if now - ts < _TEST_COHORT_CACHE_TTL_SECONDS:
                    return set(payload)

    ids: set[str] = set()

    # 1. BetaCohortMember — anyone who's been invited, opted in, or
    #    had an OTA pushed. Explicitly excludes 'declined' and
    #    'excluded' states (those are out of the cohort).
    try:
        rows = db.execute(text("""
            SELECT DISTINCT device_id FROM beta_cohort_members
            WHERE device_id IS NOT NULL
              AND state NOT IN ('declined', 'excluded')
        """)).all()
        for (did,) in rows:
            if did:
                ids.add(did)
    except Exception:
        pass

    # 2. FirmwareDeployLog — every alpha/beta deploy attempt that
    #    reached the device (or is in flight).
    try:
        rows = db.execute(text("""
            SELECT DISTINCT device_id FROM firmware_deploy_log
            WHERE device_id IS NOT NULL
              AND cohort IN ('alpha', 'beta')
              AND status IN ('pending', 'in_flight', 'succeeded')
        """)).all()
        for (did,) in rows:
            if did:
                ids.add(did)
    except Exception:
        pass

    # 3. Any device currently on 01.01.9x firmware — per Joseph
    #    2026-04-22, that band is live alpha. Pulled from stream events
    #    (most current) with session-table fallback.
    try:
        rows = db.execute(text("""
            SELECT DISTINCT ON (device_id)
                device_id, firmware_version
            FROM telemetry_stream_events
            WHERE device_id IS NOT NULL
              AND device_id NOT LIKE 'mac:%%'
            ORDER BY device_id, sample_timestamp DESC
        """)).all()
        for did, fw in rows:
            if did and _is_alpha_firmware(fw):
                ids.add(did)
    except Exception:
        pass
    try:
        rows = db.execute(text("""
            SELECT DISTINCT ON (device_id)
                device_id, firmware_version
            FROM telemetry_sessions
            WHERE device_id IS NOT NULL
              AND device_id NOT LIKE 'mac:%%'
            ORDER BY device_id, session_start DESC
        """)).all()
        for did, fw in rows:
            if did and _is_alpha_firmware(fw):
                ids.add(did)
    except Exception:
        pass

    with _test_cohort_cache_lock:
        _test_cohort_cache = (now, frozenset(ids))
    return ids


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
