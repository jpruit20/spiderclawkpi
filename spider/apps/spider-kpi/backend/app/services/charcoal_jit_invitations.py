"""Charcoal JIT — beta invitation engine.

This module selects the top-N devices from the addressable cohort and
writes one ``CharcoalJITInvitation`` row per device. The cohort-selection
math reuses ``_build_device_burn_pool`` from ``charcoal_jit`` so this
engine never re-does the expensive JSONB decode — it runs on the same
cached pool the economic modeler uses, which means an invite preview
from the UI is cheap even at peak traffic.

Two entrypoints:

* ``preview_invitation_batch`` — read-only dry run. Returns the ranked
  candidate list + summary stats so the admin can sanity-check before
  sending. No DB writes.
* ``create_invitation_batch`` — writes ``charcoal_jit_invitations`` rows
  inside a single transaction and returns the ``batch_id`` + the same
  shape the preview returned.

Both enforce the "already invited / already subscribed" exclusion so the
same device can't land in two live batches. A device that previously
got a revoked or expired invite CAN be invited again — operator's choice.

Cohort selection shape is deliberately simple:

    rank devices by monthly lb, descending
    filter out already-invited (status in pending/accepted) and already-
    subscribed devices
    take the top ``max_invitations``

``target_percentile_floor`` still cuts the bottom of the pool (it's the
"at least this heavy" filter) and is snapshotted on each invitation row
so we can answer "what percentile was this device when we invited it?"
forever.

Token: one UUIDv4 per invitation, URL-safe. The app-side dereferences
``/api/charcoal/jit/invitations/{token}`` to resolve, then POSTs to
``/accept`` with a ``user_key`` (email).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import (
    CharcoalJITInvitation,
    CharcoalJITSubscription,
    PartnerProduct,
)
from app.services.charcoal_jit import _build_device_burn_pool

logger = logging.getLogger(__name__)


# Default invitation lifetime. 14 days is long enough to catch a weekly
# griller but short enough that unopened invites churn out so we can
# re-target the slot.
DEFAULT_EXPIRY_DAYS = 14

# Invitation statuses that reserve the device — a device in one of these
# states should NOT get another invite from a new batch.
RESERVING_STATUSES = ("pending", "accepted")

# All valid status values (used for validation on admin transitions).
ALL_STATUSES = ("pending", "accepted", "declined", "expired", "revoked")


def _macs_for_device_ids(db: Session, device_ids: list[str]) -> dict[str, str]:
    """Best-effort device_id → mac_normalized lookup.

    Uses the same JSON path the firmware routes' expression index covers
    (``raw_payload->device_data->reported->mac``). Falls back to empty if
    no telemetry_stream_events exist — the invite row is still valid,
    just missing the mac column until telemetry arrives.
    """
    if not device_ids:
        return {}
    rows = db.execute(
        text(
            """
            SELECT DISTINCT ON (device_id)
                device_id,
                lower(raw_payload->'device_data'->'reported'->>'mac') AS mac
            FROM telemetry_stream_events
            WHERE device_id = ANY(:device_ids)
              AND raw_payload->'device_data'->'reported'->>'mac' IS NOT NULL
            ORDER BY device_id, sample_timestamp DESC
            """
        ),
        {"device_ids": device_ids},
    ).all()
    out: dict[str, str] = {}
    for dev, mac in rows:
        if not mac:
            continue
        cleaned = mac.replace(":", "").replace("-", "").lower()
        if len(cleaned) == 12:
            out[dev] = cleaned
    return out


def _reserved_device_ids(db: Session) -> set[str]:
    """Devices that already have a live invitation (pending/accepted) OR
    an active subscription. These are excluded from new batches so the
    same grill can't land in two simultaneous pilots."""
    reserved: set[str] = set()

    inv_rows = db.execute(
        select(CharcoalJITInvitation.device_id).where(
            CharcoalJITInvitation.device_id.is_not(None),
            CharcoalJITInvitation.status.in_(RESERVING_STATUSES),
        )
    ).all()
    for (dev,) in inv_rows:
        if dev:
            reserved.add(dev)

    sub_rows = db.execute(
        select(CharcoalJITSubscription.device_id).where(
            CharcoalJITSubscription.device_id.is_not(None),
            CharcoalJITSubscription.status == "active",
        )
    ).all()
    for (dev,) in sub_rows:
        if dev:
            reserved.add(dev)

    return reserved


def _percentile(sorted_vals: list[float], q: float) -> float:
    """Duplicate of charcoal_jit._percentile; kept local so this module
    doesn't pull a private helper across module boundaries."""
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    idx = q * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def _rank_candidates(
    db: Session,
    *,
    partner_product_id: int,
    product_families: Optional[list[str]],
    min_cooks_in_window: int,
    lookback_days: int,
    target_percentile_floor: float,
    max_invitations: int,
    exclude_reserved: bool,
    now: datetime,
) -> tuple[PartnerProduct, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Shared cohort-selection core. Returns:

        (sku, all_eligible_sorted_desc, chosen_top_N, cohort_stats_summary)

    ``all_eligible_sorted_desc`` is the full ranked list pre-cap so the
    preview UI can show "29 eligible devices, top 25 selected, 4 held
    in reserve". ``chosen_top_N`` is the slice actually written.
    """
    sku = db.get(PartnerProduct, partner_product_id)
    if sku is None:
        raise ValueError(f"partner_product_id {partner_product_id} not found")
    bag_size_lb = int(sku.bag_size_lb or 20)
    if bag_size_lb <= 0:
        raise ValueError(f"SKU {sku.id} has no bag_size_lb — set one before inviting")
    fuel_pref = sku.fuel_type or "lump"
    fuel_key = "lump_lb_per_month" if fuel_pref == "lump" else "briq_lb_per_month"

    families_set = (
        {f.strip() for f in product_families if f and f.strip()}
        if product_families
        else None
    )

    pool = _build_device_burn_pool(db, lookback_days=lookback_days, now=now)

    eligible_all: list[dict[str, Any]] = []
    for d in pool:
        if families_set is not None and d["product_family"] not in families_set:
            continue
        if d["sessions_in_window"] < min_cooks_in_window:
            continue
        lb = d[fuel_key]
        if lb <= 0:
            continue
        eligible_all.append({
            "device_id": d["device_id"],
            "product_family": d["product_family"],
            "sessions_in_window": d["sessions_in_window"],
            "lb_per_month": lb,
        })

    # Percentile floor on the pool pre-exclusion so the cutoff reflects
    # the full fleet, not "fleet minus already-invited". Otherwise the
    # top-25% threshold would creep as we invite more people.
    lb_series = sorted(e["lb_per_month"] for e in eligible_all)
    addressable_count = len(eligible_all)
    mean_lb = sum(lb_series) / addressable_count if addressable_count else 0.0
    if target_percentile_floor > 0 and lb_series:
        threshold = _percentile(lb_series, target_percentile_floor / 100.0)
    else:
        threshold = 0.0

    # Rank descending by monthly lb.
    eligible_sorted = sorted(
        eligible_all, key=lambda d: d["lb_per_month"], reverse=True,
    )

    if threshold > 0:
        eligible_sorted = [d for d in eligible_sorted if d["lb_per_month"] >= threshold]

    # Exclusion of already-invited / already-subscribed devices, if
    # requested. Preview can be called with exclude_reserved=False to
    # show raw fleet ranking.
    reserved: set[str] = set()
    if exclude_reserved:
        reserved = _reserved_device_ids(db)
        eligible_sorted = [d for d in eligible_sorted if d["device_id"] not in reserved]

    # Percentile stamping — per-device, relative to the FULL eligible
    # cohort (not post-exclusion), so "top 10% burner" is a stable tag
    # regardless of how many of their peers we've already invited.
    cohort_mean = mean_lb
    # Precompute rank lookup on the full eligible pool for percentile
    # stamping. Ascending sort lets us binary-search the position.
    asc_series = sorted(lb_series)

    def _pct_of(lb: float) -> float:
        if not asc_series:
            return 0.0
        # Count of values strictly below `lb` / total, as percent.
        lo = 0
        hi = len(asc_series)
        while lo < hi:
            mid = (lo + hi) // 2
            if asc_series[mid] < lb:
                lo = mid + 1
            else:
                hi = mid
        return round(100.0 * lo / len(asc_series), 1)

    for d in eligible_sorted:
        d["percentile_at_invite"] = _pct_of(d["lb_per_month"])

    chosen = eligible_sorted[: max(0, int(max_invitations))]

    # Attach device_id → mac for chosen rows; the full sorted list may
    # be large, so we only resolve macs for the slice we'll write.
    mac_map = _macs_for_device_ids(db, [d["device_id"] for d in chosen])
    for d in chosen:
        d["mac_normalized"] = mac_map.get(d["device_id"])

    summary = {
        "addressable_devices": addressable_count,
        "threshold_lb_per_month": round(threshold, 3),
        "percentile_floor": round(target_percentile_floor, 1),
        "mean_lb_per_month": round(cohort_mean, 3),
        "reserved_excluded": len(reserved),
        "ranked_after_filters": len(eligible_sorted),
        "max_invitations": max(0, int(max_invitations)),
        "selected": len(chosen),
        "product_families_filter": sorted(families_set) if families_set else None,
        "min_cooks_in_window": int(min_cooks_in_window),
        "lookback_days": int(lookback_days),
        "sku": {
            "id": sku.id,
            "partner": sku.partner,
            "title": sku.title,
            "fuel_type": fuel_pref,
            "bag_size_lb": bag_size_lb,
            "retail_price_usd": round(float(sku.retail_price_usd or 0.0), 2),
        },
    }
    return sku, eligible_sorted, chosen, summary


def preview_invitation_batch(
    db: Session,
    *,
    partner_product_id: int,
    product_families: Optional[list[str]] = None,
    min_cooks_in_window: int = 1,
    lookback_days: int = 90,
    target_percentile_floor: float = 75.0,
    max_invitations: int = 50,
    exclude_reserved: bool = True,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Dry-run preview — what would happen if we hit Send right now.

    Returns the same shape ``create_invitation_batch`` returns, minus the
    ``batch_id`` / invitation_token / persisted row IDs. The UI shows
    this in a "confirm before send" dialog so the operator can sanity-
    check the cohort slice before committing.
    """
    now = now or datetime.now(timezone.utc)
    sku, _all, chosen, summary = _rank_candidates(
        db,
        partner_product_id=partner_product_id,
        product_families=product_families,
        min_cooks_in_window=min_cooks_in_window,
        lookback_days=lookback_days,
        target_percentile_floor=target_percentile_floor,
        max_invitations=max_invitations,
        exclude_reserved=exclude_reserved,
        now=now,
    )
    # Preview of the candidate slice.
    candidates_out = [
        {
            "device_id": d["device_id"],
            "mac_normalized": d.get("mac_normalized"),
            "product_family": d["product_family"],
            "sessions_in_window": d["sessions_in_window"],
            "lb_per_month": round(d["lb_per_month"], 2),
            "percentile_at_invite": d["percentile_at_invite"],
        }
        for d in chosen
    ]
    return {
        "ok": True,
        "preview": True,
        "computed_at": now.isoformat(),
        "summary": summary,
        "candidates": candidates_out,
    }


def create_invitation_batch(
    db: Session,
    *,
    partner_product_id: int,
    product_families: Optional[list[str]] = None,
    min_cooks_in_window: int = 1,
    lookback_days: int = 90,
    target_percentile_floor: float = 75.0,
    max_invitations: int = 50,
    margin_pct: float = 10.0,
    expiry_days: int = DEFAULT_EXPIRY_DAYS,
    invited_by: Optional[str] = None,
    notes: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Write ``charcoal_jit_invitations`` rows for the top cohort.

    Reservation (already-invited / already-subscribed) exclusion is
    always on for real sends — operator cannot bypass it.

    Returns ``{ok, batch_id, summary, invitations}`` where ``invitations``
    is the list of persisted rows with their tokens (so the app-side
    caller can distribute them immediately if needed).
    """
    now = now or datetime.now(timezone.utc)
    expiry_days = max(1, min(int(expiry_days), 90))
    max_invitations = max(1, min(int(max_invitations), 500))

    sku, _all, chosen, summary = _rank_candidates(
        db,
        partner_product_id=partner_product_id,
        product_families=product_families,
        min_cooks_in_window=min_cooks_in_window,
        lookback_days=lookback_days,
        target_percentile_floor=target_percentile_floor,
        max_invitations=max_invitations,
        exclude_reserved=True,
        now=now,
    )

    if not chosen:
        return {
            "ok": False,
            "error": "no eligible devices after filters + exclusions",
            "summary": summary,
            "candidates": [],
        }

    batch_id = str(uuid.uuid4())
    expires_at = now + timedelta(days=expiry_days)
    cohort_params = {
        "product_families": summary["product_families_filter"],
        "min_cooks_in_window": summary["min_cooks_in_window"],
        "lookback_days": summary["lookback_days"],
        "target_percentile_floor": summary["percentile_floor"],
        "max_invitations": summary["max_invitations"],
        "margin_pct": round(float(margin_pct), 2),
        "threshold_lb_per_month": summary["threshold_lb_per_month"],
    }
    fuel_pref = sku.fuel_type or "lump"
    bag_size_lb = int(sku.bag_size_lb or 20)

    rows: list[CharcoalJITInvitation] = []
    for d in chosen:
        row = CharcoalJITInvitation(
            batch_id=batch_id,
            invitation_token=str(uuid.uuid4()),
            device_id=d["device_id"],
            mac_normalized=d.get("mac_normalized"),
            user_key=None,  # resolved at acceptance time
            partner_product_id=sku.id,
            bag_size_lb=bag_size_lb,
            fuel_preference=fuel_pref,
            margin_pct=float(margin_pct),
            addressable_lb_per_month=float(d["lb_per_month"]),
            percentile_at_invite=float(d["percentile_at_invite"]),
            sessions_in_window_at_invite=int(d["sessions_in_window"]),
            product_family_at_invite=d["product_family"],
            cohort_params_json=cohort_params,
            status="pending",
            invited_at=now,
            expires_at=expires_at,
            invited_by=invited_by,
            notes=notes,
        )
        db.add(row)
        rows.append(row)

    db.commit()
    for row in rows:
        db.refresh(row)

    return {
        "ok": True,
        "preview": False,
        "batch_id": batch_id,
        "computed_at": now.isoformat(),
        "summary": {**summary, "expires_at": expires_at.isoformat(), "expiry_days": expiry_days},
        "invitations": [serialize_invitation(r) for r in rows],
    }


def serialize_invitation(row: CharcoalJITInvitation) -> dict[str, Any]:
    """Shape used by both admin list endpoints and the app-side resolve
    endpoint. Sensitive fields (notes, invited_by) can be redacted at
    the endpoint layer if we expose this to non-admin callers."""
    return {
        "id": row.id,
        "batch_id": row.batch_id,
        "invitation_token": row.invitation_token,
        "device_id": row.device_id,
        "mac_normalized": row.mac_normalized,
        "user_key": row.user_key,
        "partner_product_id": row.partner_product_id,
        "bag_size_lb": row.bag_size_lb,
        "fuel_preference": row.fuel_preference,
        "margin_pct": row.margin_pct,
        "addressable_lb_per_month": row.addressable_lb_per_month,
        "percentile_at_invite": row.percentile_at_invite,
        "sessions_in_window_at_invite": row.sessions_in_window_at_invite,
        "product_family_at_invite": row.product_family_at_invite,
        "cohort_params": row.cohort_params_json or {},
        "status": row.status,
        "invited_at": row.invited_at.isoformat() if row.invited_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "accepted_at": row.accepted_at.isoformat() if row.accepted_at else None,
        "declined_at": row.declined_at.isoformat() if row.declined_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "invited_by": row.invited_by,
        "notes": row.notes,
        "subscription_id": row.subscription_id,
    }


def revoke_invitation(
    db: Session,
    *,
    invitation_id: int,
    revoked_by: Optional[str] = None,
    reason: Optional[str] = None,
) -> dict[str, Any]:
    """Flip a pending invite to revoked. Revoked invites free the device
    back up for future batches."""
    row = db.get(CharcoalJITInvitation, invitation_id)
    if row is None:
        return {"ok": False, "error": "invitation not found"}
    if row.status != "pending":
        return {
            "ok": False,
            "error": f"cannot revoke invitation in status {row.status}",
            "invitation": serialize_invitation(row),
        }
    row.status = "revoked"
    row.revoked_at = datetime.now(timezone.utc)
    if reason:
        extra = f"[revoked: {reason}" + (f" by {revoked_by}" if revoked_by else "") + "]"
        row.notes = f"{row.notes}\n{extra}" if row.notes else extra
    db.commit()
    db.refresh(row)
    return {"ok": True, "invitation": serialize_invitation(row)}


def expire_stale_invitations(db: Session, *, now: Optional[datetime] = None) -> dict[str, Any]:
    """Mark any past-expiry pending invitations as expired. Intended for
    a daily scheduler call. Returns the count flipped.

    Kept idempotent — running it repeatedly is a no-op after the first
    pass clears everything.
    """
    now = now or datetime.now(timezone.utc)
    stale = db.execute(
        select(CharcoalJITInvitation).where(
            CharcoalJITInvitation.status == "pending",
            CharcoalJITInvitation.expires_at < now,
        )
    ).scalars().all()
    n = 0
    for row in stale:
        row.status = "expired"
        n += 1
    if n:
        db.commit()
    return {"ok": True, "expired": n, "computed_at": now.isoformat()}


def list_batches(db: Session) -> dict[str, Any]:
    """One row per batch_id with aggregate status counts + first/last
    invite timestamps. Powers the Beta rollout tab's batch history."""
    rows = db.execute(
        text(
            """
            SELECT
                batch_id,
                MIN(invited_at) AS first_invite,
                MAX(invited_at) AS last_invite,
                MIN(expires_at) AS expires_at,
                MAX(invited_by) AS invited_by,
                COUNT(*) FILTER (WHERE status = 'pending')  AS pending,
                COUNT(*) FILTER (WHERE status = 'accepted') AS accepted,
                COUNT(*) FILTER (WHERE status = 'declined') AS declined,
                COUNT(*) FILTER (WHERE status = 'expired')  AS expired,
                COUNT(*) FILTER (WHERE status = 'revoked')  AS revoked,
                COUNT(*) AS total
            FROM charcoal_jit_invitations
            GROUP BY batch_id
            ORDER BY first_invite DESC
            """
        )
    ).all()
    out = []
    for r in rows:
        (
            batch_id, first_invite, last_invite, expires_at, invited_by,
            pending, accepted, declined, expired, revoked, total,
        ) = r
        out.append({
            "batch_id": batch_id,
            "first_invite_at": first_invite.isoformat() if first_invite else None,
            "last_invite_at": last_invite.isoformat() if last_invite else None,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "invited_by": invited_by,
            "counts": {
                "pending": int(pending or 0),
                "accepted": int(accepted or 0),
                "declined": int(declined or 0),
                "expired": int(expired or 0),
                "revoked": int(revoked or 0),
                "total": int(total or 0),
            },
            "acceptance_pct": (
                round(100.0 * int(accepted or 0) / int(total), 1)
                if total else 0.0
            ),
        })
    return {"batches": out, "count": len(out)}


def get_batch(db: Session, *, batch_id: str) -> dict[str, Any]:
    """Full detail for one batch — every invitation row."""
    rows = db.execute(
        select(CharcoalJITInvitation)
        .where(CharcoalJITInvitation.batch_id == batch_id)
        .order_by(CharcoalJITInvitation.percentile_at_invite.desc().nullslast())
    ).scalars().all()
    if not rows:
        return {"ok": False, "error": "batch not found"}
    counts = {
        "pending": 0, "accepted": 0, "declined": 0, "expired": 0, "revoked": 0,
    }
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    counts["total"] = len(rows)
    first = rows[0]
    return {
        "ok": True,
        "batch_id": batch_id,
        "invited_by": first.invited_by,
        "cohort_params": first.cohort_params_json or {},
        "counts": counts,
        "invitations": [serialize_invitation(r) for r in rows],
    }


def resolve_by_token(db: Session, *, token: str) -> Optional[CharcoalJITInvitation]:
    """App-side helper — fetch an invitation by its URL token. Does NOT
    mutate status; callers check ``status`` / ``expires_at`` themselves
    before rendering the opt-in screen."""
    return db.execute(
        select(CharcoalJITInvitation).where(
            CharcoalJITInvitation.invitation_token == token,
        )
    ).scalars().first()


def normalize_mac(raw: str) -> Optional[str]:
    """Collapse separators and lowercase a mac. Returns the 12-hex form
    or ``None`` if the input doesn't resolve to a valid mac. Kept as a
    module-level helper so the route layer can reuse the exact same
    normalization the invitation-writer used on creation."""
    if not raw:
        return None
    cleaned = (
        raw.strip()
        .replace(":", "")
        .replace("-", "")
        .replace(" ", "")
        .lower()
    )
    if len(cleaned) != 12:
        return None
    try:
        int(cleaned, 16)
    except ValueError:
        return None
    return cleaned


def lookup_pending_by_mac(
    db: Session,
    *,
    mac: str,
    now: Optional[datetime] = None,
) -> Optional[CharcoalJITInvitation]:
    """Return the live pending invitation for a mac, or ``None``. Used by
    the app-side polling path (``GET /for-device/{mac}``) so the Spider
    Grills app can detect a pending invite when a user opens the app or
    pairs a grill.

    A row counts as "live" when ``status='pending'`` AND either
    ``expires_at`` is null or still in the future. If multiple rows
    match (shouldn't happen under the reservation logic but can occur
    historically), the most recently invited one wins."""
    resolved = normalize_mac(mac)
    if resolved is None:
        return None
    now = now or datetime.now(timezone.utc)
    return db.execute(
        select(CharcoalJITInvitation)
        .where(
            CharcoalJITInvitation.mac_normalized == resolved,
            CharcoalJITInvitation.status == "pending",
            (
                CharcoalJITInvitation.expires_at.is_(None)
                | (CharcoalJITInvitation.expires_at > now)
            ),
        )
        .order_by(CharcoalJITInvitation.invited_at.desc())
    ).scalars().first()


def accept_invitation(
    db: Session,
    *,
    token: str,
    user_key: str,
    shipping_zip: Optional[str] = None,
    shipping_lat: Optional[float] = None,
    shipping_lon: Optional[float] = None,
    lead_time_days: int = 5,
    safety_stock_days: int = 7,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Promote a pending invite to ``accepted`` and create the matching
    subscription. This is the one write path the Spider Grills app
    invokes when a user taps "Opt in" on the invitation screen.

    Returns ``{ok, invitation, subscription}`` or ``{ok: False, error}``.
    """
    now = now or datetime.now(timezone.utc)
    row = resolve_by_token(db, token=token)
    if row is None:
        return {"ok": False, "error": "invitation not found"}
    if row.status != "pending":
        return {
            "ok": False,
            "error": f"invitation not pending (status={row.status})",
            "invitation": serialize_invitation(row),
        }
    if row.expires_at and row.expires_at < now:
        # Opportunistically flip to expired so the status is accurate.
        row.status = "expired"
        db.commit()
        db.refresh(row)
        return {
            "ok": False,
            "error": "invitation expired",
            "invitation": serialize_invitation(row),
        }

    user_key = (user_key or "").strip()
    if not user_key:
        return {"ok": False, "error": "user_key required"}

    # Upsert subscription keyed on (device_id, user_key) to keep the
    # existing constraint honoured.
    existing = db.execute(
        select(CharcoalJITSubscription).where(
            CharcoalJITSubscription.device_id == row.device_id,
            CharcoalJITSubscription.user_key == user_key,
        )
    ).scalars().first()

    if existing is not None:
        sub = existing
        sub.status = "active"
        sub.fuel_preference = row.fuel_preference
        sub.bag_size_lb = row.bag_size_lb
        sub.lead_time_days = lead_time_days
        sub.safety_stock_days = safety_stock_days
        sub.partner_product_id = row.partner_product_id
        sub.margin_pct = float(row.margin_pct)
        if shipping_zip is not None:
            sub.shipping_zip = shipping_zip
        if shipping_lat is not None:
            sub.shipping_lat = shipping_lat
        if shipping_lon is not None:
            sub.shipping_lon = shipping_lon
    else:
        sub = CharcoalJITSubscription(
            device_id=row.device_id,
            mac_normalized=row.mac_normalized,
            user_key=user_key,
            fuel_preference=row.fuel_preference,
            bag_size_lb=row.bag_size_lb,
            lead_time_days=lead_time_days,
            safety_stock_days=safety_stock_days,
            shipping_zip=shipping_zip,
            shipping_lat=shipping_lat,
            shipping_lon=shipping_lon,
            partner_product_id=row.partner_product_id,
            margin_pct=float(row.margin_pct),
            status="active",
            enrolled_by=f"invitation:{row.invitation_token}",
        )
        db.add(sub)

    db.flush()  # populate sub.id before linking
    row.status = "accepted"
    row.accepted_at = now
    row.user_key = user_key
    row.subscription_id = sub.id
    db.commit()
    db.refresh(row)
    db.refresh(sub)

    # Initial forecast so the newly-active sub has real numbers.
    try:
        from app.services.charcoal_jit import forecast_subscription
        forecast_subscription(db, sub)
        db.commit()
        db.refresh(sub)
    except Exception:
        logger.exception("initial forecast after invitation acceptance failed")
        db.rollback()

    return {
        "ok": True,
        "invitation": serialize_invitation(row),
        "subscription_id": sub.id,
    }


def decline_invitation(
    db: Session,
    *,
    token: str,
    reason: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """User actively said no. Records the decline for cohort analytics
    ("x% declined at 25%-percentile-floor targeting")."""
    now = now or datetime.now(timezone.utc)
    row = resolve_by_token(db, token=token)
    if row is None:
        return {"ok": False, "error": "invitation not found"}
    if row.status != "pending":
        return {
            "ok": False,
            "error": f"invitation not pending (status={row.status})",
            "invitation": serialize_invitation(row),
        }
    row.status = "declined"
    row.declined_at = now
    if reason:
        extra = f"[declined: {reason}]"
        row.notes = f"{row.notes}\n{extra}" if row.notes else extra
    db.commit()
    db.refresh(row)
    return {"ok": True, "invitation": serialize_invitation(row)}
