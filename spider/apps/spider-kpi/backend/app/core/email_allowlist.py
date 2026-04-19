"""KPI email recipient allowlist — the single source of truth for who is
permitted to receive weekly / daily / quarterly / telemetry KPI digests
and push alerts from the dashboard.

The contents of the dashboard are confidential (revenue, margins, AI
activity, staff performance). Any address not listed below is rejected
at send time with an ``UnauthorizedRecipientError`` — scripts hard-fail
rather than silently leak. The ``.env`` value for
``PUSH_ALERTS_RECIPIENT_EMAIL`` is only honored if it also appears here.

To add a recipient:
    1. Edit ``KPI_RECIPIENT_ALLOWLIST`` below.
    2. Open a PR — CODEOWNERS routes the review to @jpruit20.
    3. After merge, redeploy the backend + cron scripts.
"""
from __future__ import annotations

from typing import Iterable


class UnauthorizedRecipientError(RuntimeError):
    """Raised when a KPI email send is attempted to an address not on the
    allowlist. Callers should let this propagate — silent filtering would
    defeat the purpose of the guardrail.
    """


# Lowercase, trimmed. Compared after the same normalization on input.
KPI_RECIPIENT_ALLOWLIST: frozenset[str] = frozenset({
    "joseph@spidergrills.com",
})


def _normalize(email: str) -> str:
    return (email or "").strip().lower()


def is_allowed(email: str) -> bool:
    return _normalize(email) in KPI_RECIPIENT_ALLOWLIST


def assert_allowed(recipients: str | Iterable[str]) -> list[str]:
    """Validate one or more recipients against the allowlist.

    Returns the normalized list on success. Raises
    ``UnauthorizedRecipientError`` naming the offending address(es) on
    failure so the cron log + alerting make the breach obvious.
    """
    if isinstance(recipients, str):
        candidates = [recipients]
    else:
        candidates = list(recipients)

    normalized: list[str] = []
    rejected: list[str] = []
    for raw in candidates:
        n = _normalize(raw)
        if not n:
            continue
        if n in KPI_RECIPIENT_ALLOWLIST:
            normalized.append(n)
        else:
            rejected.append(raw)

    if rejected:
        raise UnauthorizedRecipientError(
            "KPI email send blocked — recipient(s) not on allowlist: "
            + ", ".join(rejected)
            + ". Edit backend/app/core/email_allowlist.py (reviewed by @jpruit20) to add."
        )
    if not normalized:
        raise UnauthorizedRecipientError(
            "KPI email send blocked — no recipients provided."
        )
    return normalized
