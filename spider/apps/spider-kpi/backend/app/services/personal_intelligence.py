from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import FreshdeskTicket, FreshdeskTicketEvent


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data" / "personal_intelligence"
SENDER_PROFILES_PATH = DATA_DIR / "sender_profiles.json"
OVERRIDE_PATTERNS_PATH = DATA_DIR / "override_patterns.json"
DAILY_INSIGHTS_CACHE_PATH = DATA_DIR / "daily_insights.json"

DEFAULT_ACTION = "review"
THREAT_ACTIONS = {"block", "escalate_security", "quarantine"}
HIGH_PRIORITY_ARCHETYPES = {"credential_sensitive", "customer_escalation", "legal_approval"}
LOW_PRIORITY_ARCHETYPES = {"internal_fyi", "meeting_invite", "engineering_update"}

ARCHETYPE_RULES: list[dict[str, Any]] = [
    {
        "archetype": "payment_notification",
        "subject_patterns": [r"invoice", r"receipt", r"payment (received|failed|due)", r"billing", r"charge"],
        "sender_domains": ["stripe.com", "paypal.com", "bill.com", "quickbooks.com"],
        "body_keywords": ["payment", "invoice", "charged", "receipt", "paid", "billing"],
    },
    {
        "archetype": "shipment_logistics",
        "subject_patterns": [r"shipment", r"tracking", r"out for delivery", r"delivery update", r"shipping update"],
        "sender_domains": ["ups.com", "fedex.com", "usps.com", "dhl.com", "shopify.com", "amazon.com"],
        "body_keywords": ["tracking", "shipment", "carrier", "delivered", "eta", "package"],
    },
    {
        "archetype": "legal_approval",
        "subject_patterns": [r"approval required", r"signature required", r"please approve", r"legal review"],
        "sender_domains": ["docusign.net", "hellosign.com", "adobe.com", "ironcladapp.com"],
        "body_keywords": ["approve", "signature", "agreement", "legal", "consent"],
    },
    {
        "archetype": "engineering_update",
        "subject_patterns": [r"release", r"deployment", r"incident", r"build", r"hotfix", r"engineering update"],
        "sender_domains": ["github.com", "linear.app", "jira.com", "atlassian.net", "sentry.io"],
        "body_keywords": ["deploy", "release", "incident", "build", "error", "rollback", "engineering"],
    },
    {
        "archetype": "vendor_contract",
        "subject_patterns": [r"msa", r"sow", r"contract", r"renewal", r"vendor agreement"],
        "sender_domains": ["pandadoc.com", "docusign.net", "contractbook.com"],
        "body_keywords": ["contract", "renewal", "term", "vendor", "agreement", "pricing"],
    },
    {
        "archetype": "meeting_invite",
        "subject_patterns": [r"invite:", r"calendar", r"meeting", r"zoom", r"google meet"],
        "sender_domains": ["calendar.google.com", "google.com", "outlook.com", "microsoft.com", "zoom.us"],
        "body_keywords": ["meeting", "calendar", "invite", "join", "conference"],
    },
    {
        "archetype": "credential_sensitive",
        "subject_patterns": [r"password", r"reset", r"verification code", r"mfa", r"login alert", r"security alert"],
        "sender_domains": ["okta.com", "microsoft.com", "google.com", "1password.com", "duo.com"],
        "body_keywords": ["password", "verification", "otp", "security", "login", "credential"],
    },
    {
        "archetype": "customer_escalation",
        "subject_patterns": [r"urgent", r"escalat", r"disappointed", r"refund", r"supervisor", r"complaint"],
        "sender_domains": ["gmail.com", "yahoo.com", "outlook.com"],
        "body_keywords": ["angry", "escalat", "refund", "unacceptable", "lawsuit", "manager"],
    },
    {
        "archetype": "internal_fyi",
        "subject_patterns": [r"fyi", r"for your information", r"heads up", r"just sharing", r"update only"],
        "sender_domains": ["spidergrills.com", "internal", "slack.com"],
        "body_keywords": ["fyi", "heads up", "no action needed", "for visibility", "sharing"],
    },
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    _ensure_data_dir()
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _extract_domain(value: Optional[str]) -> str:
    _, email_addr = parseaddr(value or "")
    if "@" in email_addr:
        return email_addr.split("@", 1)[1].lower().strip()
    text = (value or "").strip().lower()
    if text.startswith("@"):
        text = text[1:]
    return text


def _get_subject(thread: dict[str, Any]) -> str:
    return str(thread.get("subject") or thread.get("subject_line") or "").strip()


def _get_body_preview(thread: dict[str, Any]) -> str:
    value = thread.get("body_preview") or thread.get("preview") or thread.get("body") or thread.get("description") or ""
    return str(value).strip()


def _get_sender_domain(thread: dict[str, Any]) -> str:
    raw = thread.get("sender_domain") or thread.get("domain") or thread.get("from_domain") or thread.get("sender") or thread.get("from")
    return _extract_domain(str(raw) if raw is not None else "")


def _contains_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def _keyword_hits(text: str, keywords: list[str]) -> int:
    lowered = text.lower()
    return sum(1 for keyword in keywords if keyword.lower() in lowered)


def classify_archetype(thread: dict[str, Any]) -> dict[str, str]:
    subject = _get_subject(thread)
    body_preview = _get_body_preview(thread)
    sender_domain = _get_sender_domain(thread)
    combined = f"{subject}\n{body_preview}"

    best_archetype = "internal_fyi"
    best_score = -1

    for rule in ARCHETYPE_RULES:
        score = 0
        if _contains_any(subject, rule["subject_patterns"]):
            score += 3
        if sender_domain and sender_domain in rule["sender_domains"]:
            score += 3
        score += min(_keyword_hits(combined, rule["body_keywords"]), 3)
        if score > best_score:
            best_archetype = rule["archetype"]
            best_score = score

    if best_score <= 0:
        if sender_domain.endswith("spidergrills.com"):
            best_archetype = "internal_fyi"
        elif re.search(r"invoice|payment|billing", combined, re.IGNORECASE):
            best_archetype = "payment_notification"
        elif re.search(r"tracking|shipment|delivery", combined, re.IGNORECASE):
            best_archetype = "shipment_logistics"
        elif re.search(r"password|verification|security", combined, re.IGNORECASE):
            best_archetype = "credential_sensitive"

    return {"archetype": best_archetype}


def attach_archetype(thread: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(thread)
    enriched.update(classify_archetype(thread))
    return enriched


def _normalize_event_row(ticket: FreshdeskTicket, event: Optional[FreshdeskTicketEvent]) -> dict[str, Any]:
    payload = ticket.raw_payload if isinstance(ticket.raw_payload, dict) else {}
    event_payload = event.normalized_payload if event and isinstance(event.normalized_payload, dict) else {}
    raw_event = event.raw_payload if event and isinstance(event.raw_payload, dict) else {}
    thread = {
        "ticket_id": ticket.ticket_id,
        "subject": ticket.subject or payload.get("subject") or "",
        "body_preview": payload.get("description_text") or payload.get("structured_description") or payload.get("description") or "",
        "sender": payload.get("email") or payload.get("requester", {}).get("email") or payload.get("from_email") or "",
        "sender_domain": _extract_domain(payload.get("email") or payload.get("requester", {}).get("email") or payload.get("from_email") or ""),
        "recommended_action": event_payload.get("recommended_action") or payload.get("recommended_action") or payload.get("triage_action") or DEFAULT_ACTION,
        "final_action": event_payload.get("final_action") or raw_event.get("final_action") or payload.get("final_action") or event_payload.get("action_taken") or DEFAULT_ACTION,
        "threat_level": event_payload.get("threat_level") or payload.get("threat_level") or raw_event.get("threat_level") or "none",
        "overridden": bool(
            event_payload.get("overridden")
            or raw_event.get("overridden")
            or payload.get("overridden")
            or (
                (event_payload.get("recommended_action") or payload.get("recommended_action") or payload.get("triage_action"))
                and (event_payload.get("final_action") or raw_event.get("final_action") or payload.get("final_action"))
                and (event_payload.get("recommended_action") or payload.get("recommended_action") or payload.get("triage_action"))
                != (event_payload.get("final_action") or raw_event.get("final_action") or payload.get("final_action"))
            )
        ),
        "updated_at": (ticket.updated_at_source or ticket.updated_at or ticket.created_at_source or ticket.created_at).isoformat() if (ticket.updated_at_source or ticket.updated_at or ticket.created_at_source or ticket.created_at) else None,
    }
    thread.update(classify_archetype(thread))
    return thread


def _load_event_log(db: Session, limit: int = 500) -> list[dict[str, Any]]:
    tickets = db.execute(
        select(FreshdeskTicket).order_by(desc(FreshdeskTicket.updated_at_source), desc(FreshdeskTicket.updated_at), desc(FreshdeskTicket.id)).limit(limit)
    ).scalars().all()
    if not tickets:
        return []

    ticket_ids = [ticket.ticket_id for ticket in tickets if ticket.ticket_id]
    events = db.execute(
        select(FreshdeskTicketEvent)
        .where(FreshdeskTicketEvent.ticket_id.in_(ticket_ids))
        .order_by(FreshdeskTicketEvent.ticket_id, desc(FreshdeskTicketEvent.event_timestamp), desc(FreshdeskTicketEvent.id))
    ).scalars().all()

    latest_event_by_ticket: dict[str, FreshdeskTicketEvent] = {}
    for event in events:
        if event.ticket_id not in latest_event_by_ticket:
            latest_event_by_ticket[event.ticket_id] = event

    return [_normalize_event_row(ticket, latest_event_by_ticket.get(ticket.ticket_id)) for ticket in tickets]


def build_sender_profiles(db: Session, limit: int = 500) -> dict[str, Any]:
    events = _load_event_log(db, limit=limit)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in events:
        domain = item.get("sender_domain") or "unknown"
        grouped[domain].append(item)

    profiles: list[dict[str, Any]] = []
    for domain, rows in grouped.items():
        total = len(rows)
        overrides = sum(1 for row in rows if row.get("overridden"))
        threats = sum(1 for row in rows if str(row.get("threat_level") or "none").lower() not in {"none", "low", "safe"})
        final_actions = Counter(str(row.get("final_action") or DEFAULT_ACTION) for row in rows)
        avg_action = final_actions.most_common(1)[0][0] if final_actions else DEFAULT_ACTION
        override_rate = overrides / total if total else 0.0
        threat_rate = threats / total if total else 0.0
        priority_weight = round(1.0 + threat_rate * 1.5 + override_rate * 0.5 + (0.3 if domain.endswith("spidergrills.com") else 0.0), 3)
        profiles.append({
            "domain": domain,
            "avg_action": avg_action,
            "override_rate": round(override_rate, 4),
            "priority_weight": priority_weight,
            "threat_rate": round(threat_rate, 4),
            "sample_size": total,
            "updated_at": _now_iso(),
        })

    profiles.sort(key=lambda item: (-item["priority_weight"], item["domain"]))
    payload = {"generated_at": _now_iso(), "profiles": profiles}
    _write_json(SENDER_PROFILES_PATH, payload)
    return payload


def get_sender_profile(domain: str) -> dict[str, Any]:
    normalized = _extract_domain(domain)
    payload = _read_json(SENDER_PROFILES_PATH, {"profiles": []})
    for profile in payload.get("profiles", []):
        if profile.get("domain") == normalized:
            return {
                "domain": profile.get("domain", normalized),
                "avg_action": profile.get("avg_action", DEFAULT_ACTION),
                "override_rate": float(profile.get("override_rate", 0.0)),
                "priority_weight": float(profile.get("priority_weight", 1.0)),
            }
    return {
        "domain": normalized,
        "avg_action": DEFAULT_ACTION,
        "override_rate": 0.0,
        "priority_weight": 1.0,
    }


def build_override_learning(db: Session, limit: int = 500, min_count: int = 2) -> list[dict[str, Any]]:
    events = _load_event_log(db, limit=limit)
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in events:
        if not item.get("overridden"):
            continue
        archetype = item.get("archetype") or "unknown"
        domain = item.get("sender_domain") or "unknown"
        final_action = str(item.get("final_action") or DEFAULT_ACTION)
        grouped[(archetype, domain, final_action)].append(item)

    suggestions: list[dict[str, Any]] = []
    for (archetype, domain, final_action), rows in grouped.items():
        count = len(rows)
        if count < min_count:
            continue
        confidence = min(0.99, round(0.45 + math.log(count + 1, 10) * 0.35 + min(count / 10, 0.2), 3))
        suggestions.append({
            "pattern": f"{archetype}::{domain}",
            "suggested_action": final_action,
            "confidence": confidence,
            "count": count,
        })

    suggestions.sort(key=lambda item: (-item["confidence"], -item["count"], item["pattern"]))
    _write_json(OVERRIDE_PATTERNS_PATH, {"generated_at": _now_iso(), "patterns": suggestions})
    return [
        {
            "pattern": item["pattern"],
            "suggested_action": item["suggested_action"],
            "confidence": item["confidence"],
        }
        for item in suggestions
    ]


def _lookup_override_suggestion(archetype: str, domain: str) -> Optional[dict[str, Any]]:
    payload = _read_json(OVERRIDE_PATTERNS_PATH, {"patterns": []})
    key = f"{archetype}::{domain}"
    for item in payload.get("patterns", []):
        if item.get("pattern") == key:
            return item
    return None


def apply_policy(thread: dict[str, Any], sender_profile: dict[str, Any], archetype: dict[str, str] | str) -> dict[str, str]:
    archetype_value = archetype.get("archetype") if isinstance(archetype, dict) else str(archetype)
    threat_level = str(thread.get("threat_level") or "none").lower()
    recommended_action = str(thread.get("recommended_action") or DEFAULT_ACTION)
    domain = _get_sender_domain(thread) or sender_profile.get("domain") or "unknown"

    if threat_level not in {"none", "low", "safe"}:
        return {
            "adjusted_action": recommended_action,
            "reason": f"Threat protection preserved at level={threat_level}",
        }

    override_match = _lookup_override_suggestion(archetype_value, domain)
    if override_match and float(override_match.get("confidence", 0.0)) >= 0.6:
        return {
            "adjusted_action": str(override_match.get("suggested_action") or recommended_action),
            "reason": f"Override learning matched {override_match.get('pattern')} (confidence={override_match.get('confidence')})",
        }

    override_rate = float(sender_profile.get("override_rate", 0.0))
    avg_action = str(sender_profile.get("avg_action") or recommended_action)
    priority_weight = float(sender_profile.get("priority_weight", 1.0))

    if archetype_value in HIGH_PRIORITY_ARCHETYPES:
        return {
            "adjusted_action": "prioritize" if recommended_action == DEFAULT_ACTION else recommended_action,
            "reason": f"High-priority archetype={archetype_value}",
        }

    if archetype_value in LOW_PRIORITY_ARCHETYPES and override_rate < 0.15 and avg_action in {"archive", "ignore", "defer"}:
        return {
            "adjusted_action": avg_action,
            "reason": f"Low-priority archetype with stable sender history ({domain})",
        }

    if priority_weight >= 1.8 and recommended_action == DEFAULT_ACTION:
        return {
            "adjusted_action": avg_action,
            "reason": f"Sender priority weight elevated for {domain}",
        }

    return {
        "adjusted_action": recommended_action,
        "reason": f"No policy adjustment applied for archetype={archetype_value}",
    }


def enrich_thread(thread: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(thread)
    archetype = classify_archetype(thread)
    sender_profile = get_sender_profile(_get_sender_domain(thread))
    policy = apply_policy({**thread, **archetype}, sender_profile, archetype)
    enriched.update(archetype)
    enriched["sender_profile"] = {
        "domain": sender_profile["domain"],
        "avg_action": sender_profile["avg_action"],
        "override_rate": sender_profile["override_rate"],
        "priority_weight": sender_profile["priority_weight"],
    }
    enriched.update(policy)
    return enriched


def build_daily_insights(db: Session, limit: int = 500) -> dict[str, Any]:
    sender_profiles = build_sender_profiles(db, limit=limit)
    patterns = build_override_learning(db, limit=limit)
    top_domains = sender_profiles.get("profiles", [])[:5]
    override_count = sum(1 for profile in sender_profiles.get("profiles", []) if float(profile.get("override_rate", 0.0)) > 0)

    payload = {
        "generated_at": _now_iso(),
        "override_counts": {
            "domains_with_overrides": override_count,
            "patterns_detected": len(patterns),
        },
        "top_patterns": patterns[:5],
        "top_domains": [
            {
                "domain": item.get("domain"),
                "avg_action": item.get("avg_action"),
                "override_rate": item.get("override_rate"),
                "priority_weight": item.get("priority_weight"),
            }
            for item in top_domains
        ],
        "recommended_policy_updates": [
            {
                "pattern": item.get("pattern"),
                "suggested_action": item.get("suggested_action"),
                "confidence": item.get("confidence"),
            }
            for item in patterns[:5]
            if float(item.get("confidence", 0.0)) >= 0.6
        ],
    }
    _write_json(DAILY_INSIGHTS_CACHE_PATH, payload)
    return payload
