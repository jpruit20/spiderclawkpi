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
from typing import Any, Optional

import requests

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
