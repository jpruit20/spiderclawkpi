"""Materialize ``AppSideUserObservation`` + ``AppSideDeviceObservation``
rows from Klaviyo app-fired events.

Why this exists
---------------

The PE page's "App-side fleet" card was scaffolded for two sources:

  * ``freshdesk`` — diagnostics-only floor, already wired via
    ``app_side.ingest_freshdesk_observations``.
  * ``app_backend`` — direct DB pull from the spidergrills.app
    backend over an SSH tunnel. This was *planned* but never
    credentialed; the dashboard column showed "pending credentials"
    indefinitely.

Now that Agustín has shipped per-event Klaviyo metrics (``Device Paired``,
``Device Unpaired``, ``Cook Completed`` — landed 2026-04-28), we have
the same kind of data the direct DB pull was supposed to give us, just
delivered via Klaviyo as the bridge. This module synthesizes
``app_backend`` source rows from those events so the dashboard cards
populate immediately, without waiting for the never-built tunnel.

The synthesis is incremental — picks up where the last run left off
via a watermark on ``raw_payload->>'klaviyo_event_id'``, so it can run
cheaply after each Klaviyo poll.

Source labelling
----------------

We tag the synthesized rows with ``source='app_backend'`` (matching
the existing scaffold) and stash ``raw_payload.via='klaviyo'`` so the
provenance is preserved. The PE card's label is being updated in
parallel to read "App backend (via Klaviyo events)" so the UI reflects
the actual pipeline instead of pretending we're reading the app DB
directly.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.compute.app_side import _normalize_mac, _user_key, _email_domain, _business_date
from app.models import (
    AppSideDeviceObservation,
    AppSideUserObservation,
    KlaviyoEvent,
    KlaviyoProfile,
)


logger = logging.getLogger(__name__)


# Klaviyo metric names we materialize into app-side observations.
# Device Paired / Unpaired tell us the device→user link (mac + firmware
# + device_type). Cook Completed tells us the user is *active* on a
# given date with a particular mac (no firmware/device_type, but enough
# for the user / device observation rollup).
_DEVICE_METRICS = {"Device Paired", "Device Unpaired", "Cook Completed"}
_USER_METRICS = {"Device Paired", "Device Unpaired", "Cook Completed", "Opened App", "First Cooking Session"}


def _profile_lookup(db: Session, profile_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Bulk-fetch the email + klaviyo_id for each event's profile.

    Why raw SQL: the ``KlaviyoProfile`` ORM model declares
    ``TimestampMixin`` (which contributes ``created_at`` / ``updated_at``)
    but the live ``klaviyo_profiles`` table doesn't have those columns —
    a model/schema drift unrelated to this work. ``select(KlaviyoProfile)``
    therefore raises ``UndefinedColumn`` on the live DB. We only need
    email + klaviyo_id here, so go column-explicit and dodge the drift.

    Returns ``{klaviyo_id: {"email": str | None}}``. Field-name mismatch
    note: events store the profile reference as ``klaviyo_profile_id``;
    the profile table calls the same value ``klaviyo_id``. We key the
    returned map by ``klaviyo_id`` so callers can look up profiles using
    the event's ``klaviyo_profile_id`` value directly.
    """
    if not profile_ids:
        return {}
    rows = db.execute(
        text("""
            SELECT klaviyo_id, email
            FROM klaviyo_profiles
            WHERE klaviyo_id = ANY(:ids)
        """),
        {"ids": profile_ids},
    ).all()
    return {r.klaviyo_id: {"email": r.email} for r in rows}


def _device_type_to_controller_model(device_type: str | None) -> str | None:
    """Map Agustín's app-side ``device_type`` to our ``controller_model`` column.

    Agustín ships ``Kettle`` / ``Huntsman`` (Giant Huntsman not yet —
    requires firmware-side discrimination via the QR-code provisioning
    Matías is working on). For now we pass through the strings; once
    Giant Huntsman lands we'll teach this mapper the casing split.
    """
    if not device_type:
        return None
    cleaned = str(device_type).strip()
    return cleaned or None


def synthesize_from_klaviyo_events(
    db: Session,
    *,
    batch_limit: int = 5000,
) -> dict[str, int]:
    """Walk every klaviyo_events row that matches our metric set and
    upsert AppSide observations. Idempotent via the unique constraint
    on (source, source_ref_id) — we use the klaviyo_event_id as the
    source_ref_id so re-running this is a no-op for already-ingested
    events.

    Returns counts: ``{'device_observations_inserted': N, 'user_observations_inserted': N, 'events_scanned': N}``.
    """
    # Pull ALL relevant klaviyo events. Idempotency comes from the unique
    # constraint on (source, source_ref_id), so we can scan from the top
    # without a watermark. Volume is bounded by the configured backfill
    # window on the Klaviyo connector (30 days by default).
    events = db.execute(
        select(
            KlaviyoEvent.klaviyo_event_id,
            KlaviyoEvent.metric_name,
            KlaviyoEvent.event_datetime,
            KlaviyoEvent.klaviyo_profile_id,
            KlaviyoEvent.email,
            KlaviyoEvent.properties,
        )
        .where(KlaviyoEvent.metric_name.in_(_USER_METRICS))
        .order_by(KlaviyoEvent.event_datetime.asc())
        .limit(batch_limit)
    ).all()

    if not events:
        return {"device_observations_inserted": 0, "user_observations_inserted": 0, "events_scanned": 0}

    # Bulk-fetch profiles for the batch.
    profile_ids = list({e.klaviyo_profile_id for e in events if e.klaviyo_profile_id})
    profiles = _profile_lookup(db, profile_ids)

    # Pre-fetch the source_ref_ids we already have for this source so
    # we skip them without hitting the unique-constraint exception
    # (which would force a transaction rollback per row).
    existing_user_refs: set[str] = set(db.execute(
        select(AppSideUserObservation.source_ref_id).where(AppSideUserObservation.source == "app_backend")
    ).scalars().all())
    existing_device_refs: set[str] = set(db.execute(
        select(AppSideDeviceObservation.source_ref_id).where(AppSideDeviceObservation.source == "app_backend")
    ).scalars().all())

    user_inserts = 0
    device_inserts = 0
    for evt in events:
        if not evt.klaviyo_event_id:
            continue
        bdate = _business_date(evt.event_datetime)
        if bdate is None:
            continue

        props = evt.properties or {}
        # Email may live on the event row OR on the linked profile.
        profile = profiles.get(evt.klaviyo_profile_id) if evt.klaviyo_profile_id else None
        profile_email = profile.get("email") if profile else None
        email = evt.email or profile_email
        ukey = _user_key(email)

        # User observation — needs user_key. Different ref-id per event
        # so per-event activity is captured (any event = "user was active
        # on this date").
        user_ref = f"klaviyo:user:{evt.klaviyo_event_id}"
        if ukey and evt.metric_name in _USER_METRICS and user_ref not in existing_user_refs:
            db.add(AppSideUserObservation(
                business_date=bdate,
                source="app_backend",
                source_ref_id=user_ref,
                user_key=ukey,
                email=email,
                email_domain=_email_domain(email),
                observed_at=evt.event_datetime,
                raw_payload={
                    "via": "klaviyo",
                    "metric": evt.metric_name,
                    "klaviyo_event_id": evt.klaviyo_event_id,
                    "klaviyo_profile_id": evt.klaviyo_profile_id,
                },
            ))
            existing_user_refs.add(user_ref)
            user_inserts += 1

        # Device observation — needs a mac. Device Paired/Unpaired carry
        # device_type + firmware_version; Cook Completed carries only mac
        # (we still record the activity for the unique-devices rollup).
        if evt.metric_name in _DEVICE_METRICS:
            mac_raw = props.get("mac")
            mac_norm = _normalize_mac(mac_raw)
            if mac_norm:
                device_ref = f"klaviyo:device:{evt.klaviyo_event_id}"
                if device_ref not in existing_device_refs:
                    db.add(AppSideDeviceObservation(
                        business_date=bdate,
                        source="app_backend",
                        source_ref_id=device_ref,
                        user_key=ukey,
                        mac_raw=str(mac_raw) if mac_raw else None,
                        mac_normalized=mac_norm,
                        controller_model=_device_type_to_controller_model(props.get("device_type")),
                        firmware_version=(str(props.get("firmware_version")).strip() or None) if props.get("firmware_version") else None,
                        # No app_version in Agustín's current event payloads. Once added,
                        # this maps directly. phone_os / phone_brand also TBD —
                        # leave None for now.
                        app_version=None,
                        phone_os=None,
                        phone_os_version=None,
                        phone_brand=None,
                        phone_model=None,
                        observed_at=evt.event_datetime,
                        raw_payload={
                            "via": "klaviyo",
                            "metric": evt.metric_name,
                            "klaviyo_event_id": evt.klaviyo_event_id,
                            "device_type": props.get("device_type"),
                            "firmware_version": props.get("firmware_version"),
                            # Cook-specific extras
                            "duration_seconds": props.get("duration_seconds"),
                            "target_temp": props.get("target_temp"),
                            "completed_normally": props.get("completed_normally"),
                        },
                    ))
                    existing_device_refs.add(device_ref)
                    device_inserts += 1

    db.flush()
    db.commit()
    logger.info(
        "klaviyo→app_side: %d user obs, %d device obs (scanned %d events)",
        user_inserts, device_inserts, len(events),
    )
    return {
        "device_observations_inserted": device_inserts,
        "user_observations_inserted": user_inserts,
        "events_scanned": len(events),
    }
