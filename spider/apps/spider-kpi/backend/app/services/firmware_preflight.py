"""Pre-flight checks for firmware OTA deploys.

Runs before we ever call AWS IoT. Produces a structured verdict per
device so the dashboard can show exactly why something was gated, and so
the caller has a single place to decide whether overrides are allowed.

The firmware itself re-validates ``version`` and ``expected_model`` at
``nhd_ota_validate_job`` — these checks are a UX shortcut, not the
security boundary. The only check that is *only* enforced here (not by
the firmware) is the **active-cook** gate. That matters: a device mid-
cook will happily take an OTA and interrupt a 12-hour brisket. Hard
block on Gamma, soft override on Alpha/Beta (user-approved per Joseph,
2026-04-20).

Resolution of MAC → device_id uses the same JSON expression index as
``app/api/routes/firmware.py`` so single-MAC lookups stay sub-second on
a full telemetry table.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Literal, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routes.firmware import (
    ACTIVE_COOK_WINDOW_SECONDS,
    _device_ids_for_mac,
    _latest_stream_event_for_mac,
    normalize_mac,
)
from app.core.config import get_settings
from app.models.entities import BetaCohortMember, FirmwareRelease


logger = logging.getLogger(__name__)


Cohort = Literal["alpha", "beta", "gamma"]


@dataclass
class DeviceCheck:
    device_id: str
    mac: Optional[str]
    current_version: Optional[str]
    controller_model: Optional[str]  # "huntsman" | "kettle" | None
    active_cook: bool
    last_sample_age_seconds: Optional[int]
    in_cohort: bool
    version_is_newer: Optional[bool]  # None if current unknown
    model_matches: Optional[bool]      # None if unknown

    # Derived booleans the route uses to decide blocks
    hard_block_reasons: list[str] = field(default_factory=list)
    soft_block_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "mac": self.mac,
            "current_version": self.current_version,
            "controller_model": self.controller_model,
            "active_cook": self.active_cook,
            "last_sample_age_seconds": self.last_sample_age_seconds,
            "in_cohort": self.in_cohort,
            "version_is_newer": self.version_is_newer,
            "model_matches": self.model_matches,
            "hard_block_reasons": list(self.hard_block_reasons),
            "soft_block_reasons": list(self.soft_block_reasons),
        }


@dataclass
class PreflightResult:
    release_id: int
    cohort: Cohort
    release_ok: bool
    release_reasons: list[str]
    devices: list[DeviceCheck]

    @property
    def any_hard_blocked(self) -> bool:
        return any(d.hard_block_reasons for d in self.devices)

    def deployable_device_ids(self, *, overrides: Optional[list[str]] = None) -> list[str]:
        """Return device_ids that are OK to deploy.

        Hard-blocked devices are never deployable. Soft-blocked devices
        are deployable only if the caller passed an override reason and
        the cohort permits overrides (Alpha/Beta only).
        """
        allowed_overrides = set(overrides or [])
        out = []
        for d in self.devices:
            if d.hard_block_reasons:
                continue
            if d.soft_block_reasons and d.device_id not in allowed_overrides:
                continue
            out.append(d.device_id)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id,
            "cohort": self.cohort,
            "release_ok": self.release_ok,
            "release_reasons": list(self.release_reasons),
            "devices": [d.to_dict() for d in self.devices],
        }


def _release_approved(release: FirmwareRelease, cohort: Cohort) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if cohort == "alpha" and not release.approved_for_alpha:
        reasons.append("release not approved for alpha")
    if cohort == "beta" and not release.approved_for_beta:
        reasons.append("release not approved for beta")
    if cohort == "gamma" and not release.approved_for_gamma:
        reasons.append("release not approved for gamma")
    if not release.binary_url:
        reasons.append("release.binary_url missing")
    if not release.binary_sha256:
        reasons.append("release.binary_sha256 missing")
    if not release.binary_size_bytes:
        reasons.append("release.binary_size_bytes missing")
    return (not reasons, reasons)


def _version_tuple(v: Optional[str]) -> tuple[int, ...]:
    """Parse ``"01.02.03"`` into ``(1, 2, 3)``. Matches the firmware's
    ``nhd_ota_compare_versions`` loop on digit runs."""
    if not v:
        return (0,)
    parts = []
    cur = ""
    for ch in v:
        if ch.isdigit():
            cur += ch
        else:
            if cur:
                parts.append(int(cur))
                cur = ""
    if cur:
        parts.append(int(cur))
    return tuple(parts) if parts else (0,)


def _latest_device_row(db: Session, device_id: str) -> Optional[dict[str, Any]]:
    """Find the most recent telemetry_stream_events row for ``device_id``
    and pull just the fields preflight needs. Single device_id — no MAC
    fan-out."""
    stmt = text(
        """
        SELECT id, sample_timestamp, engaged, heating,
               raw_payload->'device_data'->'reported'->>'mac' AS mac,
               raw_payload->'device_data'->'reported'->>'version' AS reported_version,
               raw_payload->'device_data'->'reported'->>'model' AS reported_model,
               grill_type
        FROM telemetry_stream_events
        WHERE device_id = :d
        ORDER BY sample_timestamp DESC NULLS LAST
        LIMIT 1
        """
    )
    row = db.execute(stmt, {"d": device_id}).mappings().first()
    return dict(row) if row else None


def _infer_controller_model(reported_model: Optional[str], grill_type: Optional[str]) -> Optional[str]:
    """Map telemetry model strings to ``"huntsman"`` / ``"kettle"``.

    Observed strings (2026-04-20 analysis):
      - ``Huntsman`` → huntsman
      - ``W:K:22:1:V``, ``Kettle22``, ``C:G:XT:1:D`` → kettle
    Both fields are consulted; reported.model wins when set.
    """
    for v in (reported_model, grill_type):
        if not v:
            continue
        s = v.strip().lower()
        if "huntsman" in s:
            return "huntsman"
        if "kettle" in s or s.startswith("w:k") or s.startswith("c:g"):
            return "kettle"
    return None


def _check_cohort_membership(
    db: Session,
    device_ids: list[str],
    release_id: int,
    cohort: Cohort,
) -> dict[str, bool]:
    """Return ``{device_id: in_cohort}``.

    * ``alpha`` — membership is not tracked in the DB; the caller supplies
      the MAC list directly, so every passed device is by definition
      "in cohort". Returns True for all.
    * ``beta`` — membership lives in ``beta_cohort_members`` with state
      ``opted_in`` or later. A device in ``invited`` state has not yet
      accepted; we treat it as NOT in cohort.
    * ``gamma`` — for now, gamma rollout targets the full field fleet, so
      any device with recent telemetry is in cohort. When gamma-wave
      membership gets its own table we swap this to a proper lookup.
    """
    if cohort == "alpha":
        return {d: True for d in device_ids}

    if cohort == "beta":
        rows = (
            db.query(BetaCohortMember.device_id)
            .filter(
                BetaCohortMember.release_id == release_id,
                BetaCohortMember.device_id.in_(device_ids),
                BetaCohortMember.state.in_(["opted_in", "ota_pushed", "evaluated"]),
            )
            .all()
        )
        in_cohort = {r[0] for r in rows}
        return {d: (d in in_cohort) for d in device_ids}

    # gamma: treat all provided devices as eligible. Future: tighten to a
    # gamma_wave_membership table once the wave scheduler persists state.
    return {d: True for d in device_ids}


def run_preflight(
    db: Session,
    *,
    release_id: int,
    cohort: Cohort,
    device_ids: Optional[list[str]] = None,
    macs: Optional[list[str]] = None,
) -> PreflightResult:
    """Resolve the device set, look up telemetry, and produce a verdict."""
    settings = get_settings()
    release = db.get(FirmwareRelease, release_id)
    if not release:
        raise ValueError(f"release_id={release_id} not found")

    release_ok, release_reasons = _release_approved(release, cohort)

    # ---- Resolve device_ids ------------------------------------------------
    resolved: list[tuple[str, Optional[str]]] = []  # (device_id, mac)
    seen: set[str] = set()

    for d in device_ids or []:
        if d and d not in seen:
            resolved.append((d, None))
            seen.add(d)

    for raw_mac in macs or []:
        mac = normalize_mac(raw_mac)
        if not mac:
            continue
        for dev_id in _device_ids_for_mac(db, mac):
            if dev_id and dev_id not in seen:
                resolved.append((dev_id, mac))
                seen.add(dev_id)

    if not resolved:
        return PreflightResult(
            release_id=release_id,
            cohort=cohort,
            release_ok=release_ok,
            release_reasons=release_reasons + ["no devices resolved from inputs"],
            devices=[],
        )

    device_id_list = [d for d, _ in resolved]
    cohort_map = _check_cohort_membership(db, device_id_list, release_id, cohort)

    now = datetime.now(timezone.utc)
    target_version = release.version
    target_model = (release.target_controller_model or "").lower() or None

    devices: list[DeviceCheck] = []
    for device_id, hinted_mac in resolved:
        row = _latest_device_row(db, device_id)
        if not row:
            # No telemetry for this device — we can still push, but the
            # user should know. Treat as soft block.
            devices.append(
                DeviceCheck(
                    device_id=device_id,
                    mac=hinted_mac,
                    current_version=None,
                    controller_model=None,
                    active_cook=False,
                    last_sample_age_seconds=None,
                    in_cohort=cohort_map.get(device_id, False),
                    version_is_newer=None,
                    model_matches=None,
                    soft_block_reasons=["no telemetry for device — cannot verify state"],
                )
            )
            continue

        sample_ts = row.get("sample_timestamp")
        age = None
        if isinstance(sample_ts, datetime):
            sample_ts_aware = sample_ts if sample_ts.tzinfo else sample_ts.replace(tzinfo=timezone.utc)
            age = int((now - sample_ts_aware).total_seconds())
        engaged = bool(row.get("engaged") or row.get("heating"))
        active_cook = (
            age is not None
            and age <= settings.firmware_ota_active_cook_window_seconds
            and engaged
        )
        current_version = row.get("reported_version")
        controller_model = _infer_controller_model(row.get("reported_model"), row.get("grill_type"))
        mac = hinted_mac or row.get("mac")
        mac = mac.lower() if isinstance(mac, str) else mac

        version_is_newer: Optional[bool] = None
        if current_version:
            version_is_newer = _version_tuple(target_version) > _version_tuple(current_version)

        model_matches: Optional[bool] = None
        if target_model and controller_model:
            model_matches = (target_model == controller_model)

        hard: list[str] = []
        soft: list[str] = []

        if not release_ok:
            hard.extend(release_reasons)

        if not cohort_map.get(device_id, False):
            hard.append(f"device not a member of {cohort} cohort for this release")

        if version_is_newer is False:
            hard.append(
                f"device already on {current_version}; target {target_version} is not newer"
            )

        if model_matches is False:
            hard.append(
                f"controller model mismatch: device is {controller_model}, target {target_model}"
            )

        if active_cook:
            if cohort == "gamma":
                hard.append("device is in active cook — gamma rollouts are hard-blocked during cooks")
            else:
                soft.append("device is in active cook — override required (Alpha/Beta only)")

        devices.append(
            DeviceCheck(
                device_id=device_id,
                mac=mac,
                current_version=current_version,
                controller_model=controller_model,
                active_cook=active_cook,
                last_sample_age_seconds=age,
                in_cohort=cohort_map.get(device_id, False),
                version_is_newer=version_is_newer,
                model_matches=model_matches,
                hard_block_reasons=hard,
                soft_block_reasons=soft,
            )
        )

    return PreflightResult(
        release_id=release_id,
        cohort=cohort,
        release_ok=release_ok,
        release_reasons=release_reasons,
        devices=devices,
    )
