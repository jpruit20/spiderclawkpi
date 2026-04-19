"""Email archetype classifier — extends personal_intelligence for
info@spidergrills.com archival ingest.

Adds DTC-specific archetypes Joseph cares about more than the generic
Freshdesk-originated set (supplier_discussion, partnership_inquiry,
press_inquiry, investor_advisor, warranty_issue, wholesale_inquiry,
creator_influencer, logistics_operations), then falls through to the
existing archetype classifier for anything not matched.

Also does lightweight entity extraction: company/brand names mentioned
in the email, which powers future lore queries like "show me all
emails mentioning [Vendor X]."

Classification is keyword+rule based — fast, deterministic, explainable.
Good for ~60k historical messages in one ingest pass. Opus-driven
semantic classification layered on top later if precision demands it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from app.services.personal_intelligence import (
    ARCHETYPE_RULES as GENERIC_ARCHETYPE_RULES,
    classify_archetype as _classify_generic_archetype,
)


# DTC-specific archetypes checked BEFORE falling through to the generic
# personal_intelligence rules. Order matters — first strong match wins.
EMAIL_ARCHETYPE_RULES: list[dict[str, Any]] = [
    {
        "archetype": "warranty_issue",
        "subject_patterns": [
            r"\bwarranty\b", r"\breplacement\b.*\b(request|needed|please)\b",
            r"\bdefective\b", r"\bbroken\b.{0,40}\b(probe|grill|controller|venom)\b",
            r"\bnot working\b.{0,30}\b(probe|grill|controller|venom|spider)\b",
            r"\bstopped working\b",
        ],
        "sender_domains": [],  # any inbound
        "body_keywords": [
            "warranty", "defective", "broken", "replacement", "stopped working",
            "malfunction", "doesn't work", "no longer works",
        ],
    },
    {
        "archetype": "supplier_discussion",
        "subject_patterns": [
            r"\b(quote|quotation|invoice)\b",
            r"\b(PO|purchase order)\b", r"\bshipment.*\b(vendor|supplier|factory)",
            r"\bMOQ\b", r"\blead time\b",
        ],
        "sender_domains": [],
        "body_keywords": [
            "MOQ", "minimum order", "lead time", "unit price", "FOB", "BOM",
            "bill of materials", "tooling", "production run", "factory",
            "manufacturer", "supplier", "vendor quote",
        ],
    },
    {
        "archetype": "partnership_inquiry",
        "subject_patterns": [
            r"\bpartnership\b", r"\bcollab(oration)?\b",
            r"\b(wholesale|reseller|distributor|dealer)\b",
            r"\bcross[- ]promo\b",
        ],
        "sender_domains": [],
        "body_keywords": [
            "partnership", "collab", "wholesale", "reseller", "distributor",
            "dealer program", "cross-promotion", "joint", "co-branded",
        ],
    },
    {
        "archetype": "wholesale_inquiry",
        "subject_patterns": [
            r"\bwholesale\b", r"\bB2B\b", r"\b(retail|retailer) (inquiry|account)\b",
            r"\bpricing.*\b(tier|bulk|volume)\b",
        ],
        "sender_domains": [],
        "body_keywords": [
            "wholesale pricing", "B2B", "retail account", "bulk pricing",
            "volume discount", "dealer", "retail partner",
        ],
    },
    {
        "archetype": "press_inquiry",
        "subject_patterns": [
            r"\b(press|media) (inquiry|request|kit)\b",
            r"\binterview request\b", r"\bstory idea\b",
            r"\bpodcast.*\b(guest|invite)\b",
            r"\breview(er)? (sample|unit|request)\b",
            r"\bfeature.*\b(article|magazine|blog)\b",
        ],
        "sender_domains": [
            "wired.com", "seriouseats.com", "foodandwine.com", "bonappetit.com",
            "epicurious.com", "theverge.com", "engadget.com", "nyt.com",
            "wsj.com", "forbes.com", "cnet.com", "popsci.com",
        ],
        "body_keywords": [
            "press inquiry", "media inquiry", "press kit", "interview",
            "story idea", "feature", "review sample", "review unit", "journalist",
            "editor", "podcast guest",
        ],
    },
    {
        "archetype": "creator_influencer",
        "subject_patterns": [
            r"\binfluencer\b", r"\b(content|social media) creator\b",
            r"\bsponsored (post|content|video)\b", r"\b(youtube|tiktok|instagram) (collab|review)\b",
            r"\baffiliate\b",
        ],
        "sender_domains": [],
        "body_keywords": [
            "influencer", "content creator", "sponsored post", "brand ambassador",
            "affiliate", "TikTok", "YouTube channel", "Instagram", "audience",
            "followers", "subscribers",
        ],
    },
    {
        "archetype": "investor_advisor",
        "subject_patterns": [
            r"\b(investor|investment) (intro|meeting|update|memo)\b",
            r"\b(term sheet|cap table|SAFE)\b",
            r"\b(seed|series [AaBb]|pre[- ]seed) (round|funding)\b",
            r"\b(VC|venture) intro\b",
            r"\b(board|advisor) meeting\b",
        ],
        "sender_domains": [],
        "body_keywords": [
            "term sheet", "cap table", "SAFE", "convertible note", "valuation",
            "investor update", "board meeting", "advisor", "seed round", "Series A",
            "venture", "pro rata", "diligence", "data room",
        ],
    },
    {
        "archetype": "logistics_operations",
        "subject_patterns": [
            r"\bcustoms\b", r"\bduties\b", r"\b3PL\b",
            r"\b(freight|LTL|FTL)\b",
            r"\b(import|export|clearance)\b",
            r"\btariff\b",
        ],
        "sender_domains": ["fedex.com", "ups.com", "dhl.com", "usps.com"],
        "body_keywords": [
            "customs clearance", "duties", "tariff", "3PL", "freight forwarder",
            "import", "export", "bill of lading", "container", "LCL", "FCL",
            "inland freight", "broker",
        ],
    },
    {
        "archetype": "customer_escalation",
        "subject_patterns": [
            r"\b(refund|chargeback)\b.{0,40}(demand|insist|require)",
            r"\burgent\b.*\b(order|refund|response)\b",
            r"\b(lawyer|attorney|legal action)\b",
            r"\b(BBB|Better Business Bureau)\b",
            r"\b(unacceptable|disappointed)\b",
        ],
        "sender_domains": [],
        "body_keywords": [
            "unacceptable", "disappointed", "refund demand", "chargeback",
            "attorney", "lawyer", "BBB", "Better Business Bureau", "small claims",
            "lawsuit", "manager please", "supervisor",
        ],
    },
]


# Entity extraction — very lightweight, catches obvious product/company
# mentions for future lore queries. We're after high precision over recall;
# if it's uncertain, skip.
SPIDER_PRODUCTS = re.compile(
    r"\b(Venom(?:\s+XL)?|Huntsman|Tarantula|pit probe|meat probe|Spider Grill|SpiderGrill|controller)\b",
    re.IGNORECASE,
)
FIRMWARE_VERSION = re.compile(r"\b(?:FW|firmware|version|v)[\s:]*(\d{1,2}\.\d{1,2}\.\d{1,3})\b", re.IGNORECASE)


@dataclass
class EmailClassification:
    archetype: str
    archetype_source: str  # email_rule | generic_rule | fallback
    confidence: float
    topic_tags: list[str]
    mentioned_entities: dict[str, list[str]]


def _any_match(text: str, patterns: list[str]) -> Optional[str]:
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            return p
    return None


def _keyword_hits(text: str, keywords: list[str]) -> int:
    lowered = text.lower()
    return sum(1 for keyword in keywords if keyword.lower() in lowered)


def _classify_email_archetype(
    subject: str, body: str, sender_domain: str
) -> tuple[Optional[str], float, Optional[str]]:
    """Try email-specific archetypes first. Returns
    (archetype, confidence, matched_rule) or (None, 0.0, None)."""
    combined = f"{subject}\n{body}"
    best: tuple[Optional[str], float, Optional[str]] = (None, 0.0, None)

    for rule in EMAIL_ARCHETYPE_RULES:
        score = 0
        matched: Optional[str] = None

        subj_match = _any_match(subject, rule["subject_patterns"])
        if subj_match:
            score += 4
            matched = subj_match

        if sender_domain and sender_domain in rule["sender_domains"]:
            score += 3

        kw_hits = _keyword_hits(combined, rule["body_keywords"])
        score += min(kw_hits, 3)

        if score >= 4:  # need a real signal, not just one keyword
            confidence = min(0.95, 0.55 + score * 0.08)
            if confidence > best[1]:
                best = (rule["archetype"], confidence, matched)

    return best


def _extract_entities(subject: str, body: str) -> dict[str, list[str]]:
    combined = f"{subject}\n{body}"
    products = sorted({m.group(0) for m in SPIDER_PRODUCTS.finditer(combined)})
    firmware = sorted({m.group(1) for m in FIRMWARE_VERSION.finditer(combined)})
    return {
        **({"products": products} if products else {}),
        **({"firmware_versions": firmware} if firmware else {}),
    }


def classify_email(
    subject: Optional[str],
    body_text: Optional[str],
    from_address: Optional[str] = None,
    labels: Optional[list[str]] = None,
) -> EmailClassification:
    """Classify an email. Returns archetype + confidence + topic tags +
    entities. Never raises — on any error returns a fallback classification.
    """
    subject = (subject or "").strip()
    body_text = (body_text or "").strip()
    from_address = (from_address or "").strip().lower()
    sender_domain = from_address.rsplit("@", 1)[-1] if "@" in from_address else ""

    # Try email-specific archetypes first.
    archetype, conf, _matched = _classify_email_archetype(subject, body_text, sender_domain)
    archetype_source = "email_rule"

    if archetype is None:
        # Fall through to generic personal_intelligence classifier.
        thread = {
            "subject": subject,
            "body_preview": body_text[:2000],
            "sender": from_address,
            "sender_domain": sender_domain,
        }
        generic = _classify_generic_archetype(thread)
        archetype = generic.get("archetype", "internal_fyi")
        archetype_source = "generic_rule"
        conf = 0.50  # generic fallthrough → modest confidence

    # Topic tags derived from labels + keywords.
    topic_tags: list[str] = []
    label_list = [str(l).lower() for l in (labels or [])]
    if any("shipping" in l for l in label_list):
        topic_tags.append("shipping")
    if any("refund" in l or "return" in l for l in label_list):
        topic_tags.append("returns_refunds")
    if archetype in {"supplier_discussion", "logistics_operations"}:
        topic_tags.append("ops_supply_chain")
    if archetype in {"partnership_inquiry", "wholesale_inquiry"}:
        topic_tags.append("growth_partnerships")
    if archetype in {"press_inquiry", "creator_influencer"}:
        topic_tags.append("pr_marketing")
    if archetype in {"warranty_issue", "customer_escalation"}:
        topic_tags.append("cx_escalation")

    # Lightweight entity extraction.
    entities = _extract_entities(subject, body_text)

    return EmailClassification(
        archetype=archetype,
        archetype_source=archetype_source,
        confidence=round(conf, 3),
        topic_tags=sorted(set(topic_tags)),
        mentioned_entities=entities,
    )
