"""WISMO classifier — identifies "where is my order" support tickets.

CX thesis (Joseph, 2026-04-18): customers should not be reaching out
to ask where their order is. If they are, we're failing to proactively
communicate about shipping delays, tracking, ETAs. This classifier
powers the WISMO KPI whose target is zero (or close to it) — every
WISMO ticket represents a communication gap on our side.

The classifier is keyword-based to start; it's deterministic, cheap,
and explainable. An AI pass can be layered on top later if precision
proves insufficient.

False-positive guardrails:
  * Positive-signal phrases ("been delivered", "arrived", "was
    delivered") downgrade to not-WISMO even if a WISMO phrase appears.
  * Order-confirmation emails ("Re: Order #X confirmed") are filtered
    out — those are Shopify-side confirmations in inbox, not customer
    asking.
  * Known non-WISMO topics ("refund", "warranty", "return", "replacement")
    are excluded even if they mention an order number.

What counts as WISMO:
  - Direct question about order/shipment status
  - Complaint about not receiving an order
  - Request for tracking info
  - Asking when something will ship
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


# Phrases that strongly imply "where is my order" intent.
WISMO_PHRASES = [
    r"where'?s my (order|shipment|package|item|product)",
    r"where is my (order|shipment|package|item|product)",
    r"when (will|should) (my|this|the) (order|shipment|package) (ship|arrive)",
    r"haven'?t (received|gotten|got)",
    r"have(n't| not) received",
    r"has(n't| not) (arrived|shipped|been sent)",
    r"not (yet )?(received|arrived|shipped)",
    r"(still )?waiting (for|on) (my|the) (order|shipment|package|delivery)",
    r"order (number )?(status|update)",
    r"order\s*#?\s*\d+\s*(status|update|where|when|tracking)",
    r"tracking (number|info|info\?|information)",
    r"shipping (status|update|delay|info)",
    r"where can i (track|find)",
    r"check (on )?(my|the) (order|shipment|package)",
    r"(didn'?t|did not) (receive|get)",
    r"(order|package|shipment) (never|not) (arrived|shipped|came)",
    r"still hasn'?t (arrived|shipped|come|shown up)",
    r"delivery (status|update|delay|eta)",
    r"when will (my|this|the) (order|shipment) (arrive|be delivered|ship)",
]

# Keywords that, combined with an order number reference, signal WISMO.
LIGHT_SIGNALS = [
    "status?", "status:", "status ", "status\n",
    "where", "when",
]

ORDER_REFERENCE = re.compile(r"(order|shipment|package)\s*#?\s*\d{4,}", re.IGNORECASE)

# Phrases that indicate the order already arrived — suppress false positives.
DELIVERED_PHRASES = [
    r"(been|was|has been|is) delivered",
    r"arrived (today|yesterday|fine|safely)",
    r"received (my|the|it|my order)",
    r"got (my|the) (order|package)",
    r"package (has )?arrived",
]

# Subject/body topics that override WISMO intent.
NON_WISMO_OVERRIDES = [
    "refund", "return", "warranty", "replacement", "defective",
    "cancel", "cancellation", "cancelled", "wrong (item|product|model)",
    "missing (part|piece|component|item from)", "price match",
    "discount code", "promo code",
    # Order-confirmation emails (Shopify forwards these; not customers asking)
    "order #.+ confirmed", "your order is on the way", "has been shipped",
    "has shipped", "shipped:", "tracking info for your order",
    "shipment (notification|confirmation)",
    # Military discount-type inquiries
    "military discount",
]


@dataclass
class WismoResult:
    is_wismo: bool
    confidence: float  # 0.0 - 1.0
    matched_rule: Optional[str]
    override_rule: Optional[str]


def _any_match(text: str, patterns: list[str]) -> Optional[str]:
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            return p
    return None


def classify_wismo(
    subject: Optional[str],
    description: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> WismoResult:
    """Return WismoResult. ``is_wismo=True`` if the ticket is asking about
    where an order is."""
    subject = (subject or "").strip()
    description = (description or "").strip()
    tags = tags or []

    # Combine for scanning — subject is higher-signal than body.
    combined = f"{subject}\n{description}".lower()

    # 1) Hard override: customer-service tags or topics that are clearly
    #    something else, even if they mention an order number.
    override = _any_match(combined, NON_WISMO_OVERRIDES)
    if override:
        # But honor an explicit WISMO tag anyway — if CX tagged it, trust them.
        tag_lower = [str(t).lower() for t in tags]
        if any(t in {"wismo", "shipping-delay", "order-status"} for t in tag_lower):
            return WismoResult(True, 0.95, matched_rule="explicit_tag", override_rule=None)
        return WismoResult(False, 0.0, matched_rule=None, override_rule=override)

    # 2) Explicit CX tags win.
    tag_lower = [str(t).lower() for t in tags]
    if any(t in {"wismo", "shipping-delay", "order-status", "where-is-my-order"} for t in tag_lower):
        return WismoResult(True, 0.95, matched_rule="explicit_tag", override_rule=None)

    # 3) Delivered-already phrases suppress WISMO regardless of other signals.
    if _any_match(combined, DELIVERED_PHRASES):
        return WismoResult(False, 0.0, matched_rule=None, override_rule="delivered_phrase")

    # 4) Strong WISMO phrases (subject OR body).
    rule = _any_match(combined, WISMO_PHRASES)
    if rule:
        # Higher confidence if the phrase is in the subject specifically.
        subj_has = _any_match(subject.lower(), WISMO_PHRASES)
        return WismoResult(True, 0.9 if subj_has else 0.75, matched_rule=rule, override_rule=None)

    # 5) Order-reference + light signal in subject — things like
    #    "Order# 21308 status?"
    if subject and ORDER_REFERENCE.search(subject):
        subj_lower = subject.lower()
        if any(sig in subj_lower for sig in LIGHT_SIGNALS):
            return WismoResult(True, 0.7, matched_rule="order_ref_light_signal", override_rule=None)

    return WismoResult(False, 0.0, matched_rule=None, override_rule=None)
