"""FedEx Web Services connector — OAuth + thin request wrapper.

Why this exists
---------------

Joseph asked (2026-04-29) to plug the dashboard into the Spider Grills
FedEx account so we can cross-check shipping costs against the ShipStation
labels we already ingest. The account is also the LTL freight carrier for
Giant Huntsman shipments, which until now have been completely invisible
to the dashboard because they don't go through ShipStation.

What's HERE
-----------

The bare-bones plumbing only:

  * ``mint_token()`` / ``_token_cache`` — OAuth client_credentials flow
    with a 5-minute pre-expiry refresh skew.
  * ``request_json()`` — generic GET/POST with retries on 429/5xx and
    transparent token refresh on 401.
  * ``health_check()`` — confirms creds + endpoint reachability without
    performing any real query. Used by the admin route + the weekly
    health audit so we know when production approval flips on.

What's NOT here yet
-------------------

The data-pulling functions (rates, freight LTL shipments, ground EOD
reports) and any DB ingestion. Those land once FedEx approves the
production project — building them against sandbox would just exercise
synthetic test data with response shapes that may or may not match prod.
The skeleton is in place so the eventual addition is small and focused.

Multi-tenant filter
-------------------

The Spider Grills FedEx account ships for multiple companies under one
umbrella login. Every API call that returns billed shipments MUST filter
to ``settings.fedex_account_number`` (the 9-digit Spider account) to
keep other companies' charges out of our reporting. Helpers added below
will enforce this at the call boundary.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import requests
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings


logger = logging.getLogger(__name__)
settings = get_settings()

TIMEOUT_SECONDS = 30
MAX_RETRIES = 4
TOKEN_REFRESH_SKEW_SECONDS = 300  # mint a fresh token 5 min before expiry


# Token cache — keyed by host so a deploy that flips between sandbox and
# production won't reuse stale tokens. Lock prevents the (rare) thundering-
# herd when multiple workers hit an expired token simultaneously.
_token_cache: dict[str, dict[str, Any]] = {}
_token_lock = threading.Lock()


class FedexConfigError(RuntimeError):
    """Raised when the FedEx connector is invoked without complete creds."""


class FedexAPIError(RuntimeError):
    """Raised when FedEx returns a non-retryable error."""

    def __init__(self, status_code: int, body: str, transaction_id: str | None = None):
        super().__init__(f"FedEx API error {status_code}: {body[:300]}")
        self.status_code = status_code
        self.body = body
        self.transaction_id = transaction_id


def _require_creds() -> tuple[str, str, str]:
    """Pull credentials from settings, raising a clear error if any are missing.

    Returns ``(api_key, api_secret, host)``. Account number is checked
    separately by callers that need it (e.g. invoice queries) since Rate
    API calls don't strictly require it.
    """
    if not settings.fedex_api_key or not settings.fedex_api_secret:
        raise FedexConfigError(
            "FEDEX_API_KEY and FEDEX_API_SECRET must be set in the env. "
            "See https://developer.fedex.com → My Projects → API Credentials."
        )
    return settings.fedex_api_key, settings.fedex_api_secret, settings.fedex_api_host


def mint_token(force: bool = False) -> str:
    """Return a valid FedEx OAuth bearer token, refreshing if needed.

    FedEx tokens are 1-hour TTL; we refresh 5 minutes before expiry to
    avoid mid-request invalidation. ``force=True`` skips the cache —
    used by the 401-retry path in ``request_json``.
    """
    api_key, api_secret, host = _require_creds()
    cache_key = f"{host}:{api_key[:8]}"

    with _token_lock:
        cached = _token_cache.get(cache_key)
        now = int(time.time())
        if not force and cached and now < (cached["expires_at"] - TOKEN_REFRESH_SKEW_SECONDS):
            return str(cached["access_token"])

        url = f"https://{host}/oauth/token"
        resp = requests.post(
            url,
            data={
                "grant_type": "client_credentials",
                "client_id": api_key,
                "client_secret": api_secret,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            timeout=TIMEOUT_SECONDS,
        )
        if resp.status_code != 200:
            txn = None
            try:
                txn = resp.json().get("transactionId")
            except Exception:
                pass
            raise FedexAPIError(resp.status_code, resp.text, transaction_id=txn)

        payload = resp.json()
        access_token = payload.get("access_token")
        expires_in = int(payload.get("expires_in") or 3599)
        if not access_token:
            raise FedexAPIError(200, "no access_token in OAuth response", None)

        _token_cache[cache_key] = {
            "access_token": access_token,
            "expires_at": now + expires_in,
            "scope": payload.get("scope"),
            "minted_at": now,
        }
        return str(access_token)


def request_json(
    method: str,
    path: str,
    *,
    json_body: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, str]] = None,
    extra_headers: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Generic FedEx API call with token, retries, and transparent 401 refresh.

    ``path`` is the path component only (e.g. ``"/rate/v1/rates/quotes"``);
    the host comes from settings so callers don't need to know about
    sandbox vs production.

    Retries on 429/500/502/503/504 with exponential-ish backoff bounded by
    the response's ``Retry-After`` header when present. Transparently
    refreshes the token once on 401 (handles edge case where a token
    cached just under the skew threshold expires mid-call).
    """
    _, _, host = _require_creds()
    url = f"https://{host}{path}"
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        token = mint_token(force=(attempt > 1 and last_error is not None and getattr(last_error, "status_code", None) == 401))
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-locale": "en_US",
        }
        if extra_headers:
            headers.update(extra_headers)
        try:
            resp = requests.request(
                method.upper(),
                url,
                json=json_body,
                params=params,
                headers=headers,
                timeout=TIMEOUT_SECONDS,
            )
            if resp.status_code in {429, 500, 502, 503, 504}:
                retry_after = resp.headers.get("Retry-After")
                delay = int(retry_after) if retry_after and retry_after.isdigit() else (attempt * 2)
                if attempt == MAX_RETRIES:
                    raise FedexAPIError(resp.status_code, resp.text, _txn(resp))
                time.sleep(min(delay, 30))
                continue
            if resp.status_code == 401 and attempt < MAX_RETRIES:
                last_error = FedexAPIError(401, resp.text, _txn(resp))
                continue
            if resp.status_code >= 400:
                raise FedexAPIError(resp.status_code, resp.text, _txn(resp))
            return resp.json()
        except requests.RequestException as exc:
            last_error = exc
            if attempt == MAX_RETRIES:
                break
            time.sleep(attempt * 2)

    raise FedexAPIError(0, f"FedEx request failed after {MAX_RETRIES} attempts: {last_error}")


def _txn(resp: requests.Response) -> Optional[str]:
    try:
        return resp.json().get("transactionId")
    except Exception:
        return None


def register_source(db: Session) -> None:
    """Make the connector visible on the System Health page.

    Idempotent — calls upsert_source_config('fedex'). Run once on
    application startup AND on every health-check call so the source
    row always exists with current configured/sync_mode metadata,
    even on a fresh DB.
    """
    # Local import to avoid a circular dependency at module load time
    # (source_health imports from app.models, which the connector
    # doesn't need at import time).
    from app.services.source_health import upsert_source_config

    is_sandbox = "sandbox" in settings.fedex_api_host.lower()
    upsert_source_config(
        db,
        "fedex",
        configured=bool(settings.fedex_api_key and settings.fedex_api_secret),
        sync_mode="poll",
        config_json={
            "host": settings.fedex_api_host,
            "environment": "sandbox" if is_sandbox else "production",
            "account_number_set": bool(settings.fedex_account_number),
        },
    )


def health_check() -> dict[str, Any]:
    """Confirm credentials + endpoint reachability without doing real work.

    Returns a small status dict consumable by the admin route and the
    weekly health audit. Distinguishes between three states:

      * ``"healthy"``     — token mints, endpoint reachable, configured.
      * ``"unconfigured"`` — env vars missing.
      * ``"sandbox"``      — works, but pointed at apis-sandbox (we want
                              prod for real cross-check value).
      * ``"error"``        — creds configured but token mint failed.
    """
    if not settings.fedex_api_key or not settings.fedex_api_secret:
        return {
            "status": "unconfigured",
            "host": settings.fedex_api_host,
            "message": "FEDEX_API_KEY / FEDEX_API_SECRET not set",
        }
    try:
        token = mint_token(force=True)
    except FedexAPIError as e:
        return {
            "status": "error",
            "host": settings.fedex_api_host,
            "http_status": e.status_code,
            "message": str(e)[:300],
            "transaction_id": e.transaction_id,
        }
    except Exception as e:  # noqa: BLE001
        return {
            "status": "error",
            "host": settings.fedex_api_host,
            "message": f"{type(e).__name__}: {e}",
        }

    cache_key = f"{settings.fedex_api_host}:{settings.fedex_api_key[:8]}"
    cached = _token_cache.get(cache_key, {})
    is_sandbox = "sandbox" in settings.fedex_api_host.lower()
    return {
        "status": "sandbox" if is_sandbox else "healthy",
        "host": settings.fedex_api_host,
        "scope": cached.get("scope"),
        "token_expires_in_s": (cached.get("expires_at", 0) - int(time.time())) if cached else None,
        "account_number_set": bool(settings.fedex_account_number),
        "token_prefix": (token[:12] + "...") if token else None,
    }


# ── Rate cross-check sync ────────────────────────────────────────────
#
# What this does: for every recent ShipStation FedEx shipment, ask the
# Rates API "what does FedEx say this label SHOULD have cost at our
# negotiated ACCOUNT rate AND at LIST rate, given the actual shipper
# postal / recipient postal / weight on the shipment?"
#
# We persist both the ACCOUNT and LIST quotes in fedex_rate_quotes so
# the dashboard can render three numbers side-by-side per shipment:
#
#   ShipStation actual  vs  FedEx ACCOUNT quote  vs  FedEx LIST quote
#
# Big delta between actual and ACCOUNT = something is wrong (wrong
# carrier account selected, dim-weight surprise, residential adjustment
# we didn't expect). Big delta between ACCOUNT and LIST = how much our
# carrier contract is saving us — useful evidence at renewal time.
#
# Why we don't pull invoice data here: the FedEx Web Services API
# doesn't expose actual invoiced amounts (FedEx restricts that to EDI
# / Compatible Program partners). For real billed truth we'll wire up
# the FBO weekly CSV email path separately. The rate-quote cross-check
# is the SECOND-best alternative — list/account rates from FedEx's
# own quoting engine, which is much more honest than ShipStation's
# pre-ship rate estimate at predicting actual invoice cost.


def _quote_payload_for_shipment(
    *,
    account_number: str,
    shipper_postal: str,
    shipper_country: str,
    recipient_postal: str,
    recipient_country: str,
    weight_lb: float,
    dimensions: Optional[dict[str, Any]] = None,
    ship_date_iso: Optional[str] = None,
    service_type: Optional[str] = None,
) -> dict[str, Any]:
    """Build a /rate/v1/rates/quotes request body from a ShipStation
    shipment's actuals. Pulls ACCOUNT + LIST in one round trip.

    ``dimensions`` (when present) materially changes the answer for
    larger packages because FedEx may bill on dimensional weight.
    Pass it through whenever ShipStation captured length/width/height.
    """
    pkg: dict[str, Any] = {"weight": {"units": "LB", "value": float(weight_lb)}}
    if dimensions:
        # ShipStation dimensions JSON is {"length": .., "width": .., "height": .., "units": "inches"}
        units = (dimensions.get("units") or "IN").upper()
        units = "IN" if units.startswith("IN") else "CM"
        pkg["dimensions"] = {
            "length": int(dimensions["length"]),
            "width": int(dimensions["width"]),
            "height": int(dimensions["height"]),
            "units": units,
        }
    body: dict[str, Any] = {
        "accountNumber": {"value": account_number},
        "requestedShipment": {
            "shipper": {"address": {"postalCode": shipper_postal, "countryCode": shipper_country}},
            "recipient": {"address": {"postalCode": recipient_postal, "countryCode": recipient_country}},
            "pickupType": "USE_SCHEDULED_PICKUP",
            "rateRequestType": ["ACCOUNT", "LIST"],
            "requestedPackageLineItems": [pkg],
        },
    }
    if ship_date_iso:
        body["requestedShipment"]["shipDateStamp"] = ship_date_iso
    if service_type:
        body["requestedShipment"]["serviceType"] = service_type
    return body


def quote_rates(
    *,
    shipper_postal: str,
    recipient_postal: str,
    weight_lb: float,
    shipper_country: str = "US",
    recipient_country: str = "US",
    dimensions: Optional[dict[str, Any]] = None,
    ship_date_iso: Optional[str] = None,
    service_type: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Call /rate/v1/rates/quotes and flatten the response into a
    flat list of (service_type, rate_type, total_charge, currency)
    rows. One call returns ALL services FedEx is willing to quote
    for this lane + weight; caller decides which ones to persist.

    The flat shape keeps caller code simple — typical use is to find
    the row whose ``service_type`` matches the actual ShipStation
    service code, then store ACCOUNT + LIST for that one service.
    """
    if not settings.fedex_account_number:
        raise FedexConfigError("FEDEX_ACCOUNT_NUMBER not set")
    body = _quote_payload_for_shipment(
        account_number=settings.fedex_account_number,
        shipper_postal=shipper_postal,
        shipper_country=shipper_country,
        recipient_postal=recipient_postal,
        recipient_country=recipient_country,
        weight_lb=weight_lb,
        dimensions=dimensions,
        ship_date_iso=ship_date_iso,
        service_type=service_type,
    )
    resp = request_json("POST", "/rate/v1/rates/quotes", json_body=body)
    rrd = resp.get("output", {}).get("rateReplyDetails", []) or []
    flat: list[dict[str, Any]] = []
    for service in rrd:
        st = service.get("serviceType")
        for rated in service.get("ratedShipmentDetails", []) or []:
            flat.append({
                "service_type": st,
                "service_name": service.get("serviceName"),
                "rate_type": rated.get("rateType"),
                "total_charge": _to_float(rated.get("totalNetCharge")),
                "currency": rated.get("currency") or "USD",
            })
    return flat


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── ShipStation → FedEx service-code mapping ──────────────────────────
#
# ShipStation's `service_code` values (e.g. "fedex_ground",
# "fedex_home_delivery", "fedex_2day") don't match FedEx's own
# `serviceType` enum (e.g. "FEDEX_GROUND", "GROUND_HOME_DELIVERY",
# "FEDEX_2_DAY"). This map keeps the rate-cross-check honest by
# selecting the right FedEx-side row for each ShipStation actual.
#
# Add entries when new ShipStation service codes show up — the
# `cross_check_rates` job logs unknown codes so we can extend
# this map without code changes to the loop.
_SHIPSTATION_TO_FEDEX_SERVICE = {
    "fedex_ground": "FEDEX_GROUND",
    "fedex_home_delivery": "GROUND_HOME_DELIVERY",
    "fedex_2day": "FEDEX_2_DAY",
    "fedex_2day_am": "FEDEX_2_DAY_AM",
    "fedex_express_saver": "FEDEX_EXPRESS_SAVER",
    "fedex_standard_overnight": "STANDARD_OVERNIGHT",
    "fedex_priority_overnight": "PRIORITY_OVERNIGHT",
    "fedex_first_overnight": "FIRST_OVERNIGHT",
    "fedex_1_day_freight": "FEDEX_1_DAY_FREIGHT",
    "fedex_2_day_freight": "FEDEX_2_DAY_FREIGHT",
    "fedex_3_day_freight": "FEDEX_3_DAY_FREIGHT",
    "fedex_first_freight": "FEDEX_FIRST_FREIGHT",
}


def _map_service(ss_code: str | None) -> Optional[str]:
    if not ss_code:
        return None
    return _SHIPSTATION_TO_FEDEX_SERVICE.get(ss_code.lower())


def cross_check_rates(db: Session, *, days: int = 7, max_shipments: int = 200) -> dict[str, Any]:
    """Walk recent ShipStation FedEx shipments, ask the Rates API for
    ACCOUNT + LIST quotes, and persist the deltas to fedex_rate_quotes.

    Idempotent — each (tracking_number, rate_type, service_type) row
    is upserted via ON CONFLICT DO UPDATE. Re-running over the same
    window is safe and refreshes stale quotes (rates can drift).

    Returns counters: shipments_scanned, quotes_inserted_or_updated,
    skipped_no_postal, skipped_unknown_service, api_errors.

    Why an explicit max_shipments cap: the Rates API has per-account
    rate limits (typically 100/min for production) and we want to
    keep this job cheap to schedule daily. With max_shipments=200 and
    one call per shipment, the job runs in ~3 minutes worst-case.
    Use the admin manual-trigger route to do larger backfills.
    """
    # Local imports to avoid circulars at module load
    from app.models import FedexRateQuote, ShipstationShipment

    started = time.monotonic()
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=days)

    # Spider-only by virtue of the existing shipstation_shipments rows
    # (the connector already filters non-Spider stores at ingest); pull
    # FedEx-only by carrier_code prefix. Order DESC so a partial run
    # covers the most recent days first.
    shipments = db.execute(
        select(ShipstationShipment)
        .where(
            ShipstationShipment.voided.is_(False),
            ShipstationShipment.shipment_cost > 0,
            ShipstationShipment.create_date >= start_dt,
            ShipstationShipment.create_date < end_dt,
            ShipstationShipment.carrier_code.like("fedex%"),
            ShipstationShipment.tracking_number.isnot(None),
        )
        .order_by(ShipstationShipment.create_date.desc())
        .limit(max_shipments)
    ).scalars().all()

    counts = {
        "shipments_scanned": len(shipments),
        "quotes_inserted_or_updated": 0,
        "skipped_no_postal": 0,
        "skipped_unknown_service": 0,
        "api_errors": 0,
    }

    for ss in shipments:
        # Need shipper postal (from raw_payload.shipFrom or warehouse),
        # recipient postal (raw_payload.shipTo.postalCode), and weight.
        ship_to = (ss.raw_payload or {}).get("shipTo") or {}
        ship_from = (ss.raw_payload or {}).get("shipFrom") or (ss.raw_payload or {}).get("advancedOptions") or {}
        recipient_postal = ship_to.get("postalCode")
        recipient_country = ship_to.get("country") or ss.ship_to_country or "US"
        # ShipFrom postal is sometimes absent (multi-warehouse account
        # without per-shipment override). Fall back to the configured
        # warehouse zip — Spider's primary is Atlanta 30303 per the
        # PRIMARY_WAREHOUSE constant in shipping_intelligence.py.
        shipper_postal = ship_from.get("postalCode") or "30303"
        shipper_country = ship_from.get("country") or "US"

        if not recipient_postal:
            counts["skipped_no_postal"] += 1
            continue

        weight_oz = float(ss.weight_oz or 0)
        weight_lb = max(weight_oz / 16.0, 0.1)  # Rates API rejects 0; floor at 0.1

        fx_service = _map_service(ss.service_code)
        if not fx_service:
            counts["skipped_unknown_service"] += 1
            logger.info("fedex.cross_check: unmapped service_code=%r tracking=%s", ss.service_code, ss.tracking_number)
            continue

        try:
            quotes = quote_rates(
                shipper_postal=shipper_postal,
                shipper_country=shipper_country,
                recipient_postal=recipient_postal,
                recipient_country=recipient_country,
                weight_lb=weight_lb,
                dimensions=ss.dimensions_json or None,
                ship_date_iso=ss.ship_date.isoformat() if ss.ship_date else None,
            )
        except FedexAPIError as e:
            counts["api_errors"] += 1
            logger.warning("fedex.cross_check: API error tracking=%s status=%s: %s",
                           ss.tracking_number, e.status_code, str(e)[:200])
            continue

        # Find matching service rows (one per rate_type)
        ss_charge = float(ss.shipment_cost or 0)
        for q in quotes:
            if q["service_type"] != fx_service:
                continue
            rate_type = q["rate_type"]
            if rate_type not in ("ACCOUNT", "LIST"):
                continue
            quoted = q["total_charge"]
            if quoted is None:
                continue
            delta = round(quoted - ss_charge, 2)

            stmt = pg_insert(FedexRateQuote).values(
                tracking_number=ss.tracking_number,
                rate_type=rate_type,
                service_type=fx_service,
                quoted_charge_usd=quoted,
                currency=q.get("currency") or "USD",
                shipstation_charge_usd=ss_charge,
                delta_usd=delta,
                raw_payload={
                    "shipper_postal": shipper_postal,
                    "recipient_postal": recipient_postal,
                    "weight_lb": weight_lb,
                    "service_name": q.get("service_name"),
                    "ss_carrier_code": ss.carrier_code,
                    "ss_service_code": ss.service_code,
                },
            ).on_conflict_do_update(
                constraint="uq_fedex_rate_quotes_tracking_type",
                set_={
                    "quoted_charge_usd": quoted,
                    "shipstation_charge_usd": ss_charge,
                    "delta_usd": delta,
                    "quoted_at": datetime.now(timezone.utc),
                    "raw_payload": {
                        "shipper_postal": shipper_postal,
                        "recipient_postal": recipient_postal,
                        "weight_lb": weight_lb,
                        "service_name": q.get("service_name"),
                        "ss_carrier_code": ss.carrier_code,
                        "ss_service_code": ss.service_code,
                    },
                },
            )
            db.execute(stmt)
            counts["quotes_inserted_or_updated"] += 1

    db.commit()
    counts["duration_ms"] = int((time.monotonic() - started) * 1000)
    logger.info("fedex.cross_check_rates: %s", counts)
    return counts
