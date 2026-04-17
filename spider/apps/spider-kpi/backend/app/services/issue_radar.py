from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import re
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import FreshdeskTicket, IssueCluster, IssueSignal, ShopifyOrderDaily, TelemetryDaily, TelemetrySession
from app.services.source_health import upsert_source_config
from app.services.telemetry import telemetry_tables_available

BUSINESS_TZ = ZoneInfo("America/New_York")

THEMES: dict[str, list[str]] = {
    "shipping": [
        "ship", "shipping", "delivery", "late", "tracking", "carrier", "label created", "lost package", "where is my order", "package", "shipment",
    ],
    "damaged_on_arrival": [
        "damaged", "broken", "dent", "arrived damaged", "doa", "cracked", "bent", "scratched", "defect on arrival", "arrived broken", "damage",
    ],
    "temperature_control_venom": [
        "temperature", "temp", "venom", "probe", "overheat", "heat", "holding temp", "temperature swing", "temperature issue", "not hot enough", "too hot", "fan not working",
    ],
    "ignition_startup": [
        "ignition", "ignite", "startup", "start up", "won't start", "wont start", "won’t start", "not lighting", "not starting", "pellet won't light", "turn on",
    ],
    "app_connectivity": [
        "app", "wifi", "bluetooth", "connect", "connection", "pair", "pairing", "firmware update", "offline", "disconnect", "mobile app", "phone app", "app not working",
    ],
    "assembly": [
        "assembly", "assemble", "screw", "bolt", "leg", "setup", "instruction", "manual", "missing part", "put together", "install", "lid not closing", "grill cover", "missing cover",
    ],
    "warranty_replacement": [
        "warranty", "replacement", "replace", "refund", "rma", "return", "claim", "exchange", "send a new", "replacement part",
    ],
    "order_admin": [
        "re: order", "order #", "order ", "confirmed", "delivered", "cancel", "missing grill cover", "cover in order",
    ],
    "product_question": [
        "huntsman", "weber", "kettle", "include", "compatibility", "fit", "fits", "question", "grill cart", "rack holder", "extender kit",
    ],
    "review_marketing": [
        "star review", "google review", "review for", "subscriber", "tiktok shop", "workspace studio", "costco", "announcement", "samples", "welcome to team huntsman",
    ],
}
NEGATIVE_THEME_TERMS: dict[str, list[str]] = {
    "shipping": ["temperature", "wifi", "bluetooth", "assembly", "warranty"],
    "app_connectivity": ["shipping", "delivery", "broken package"],
    "assembly": ["temperature", "wifi", "refund", "tracking"],
    "warranty_replacement": ["shipping update", "tracking"],
    "product_question": ["star review", "google review", "subscriber"],
    "review_marketing": ["damaged", "won't start", "temperature", "refund"],
    "order_admin": ["temperature", "wifi", "bluetooth"],
}
CO_OCCURRENCE_HINTS: dict[str, list[tuple[set[str], str, float]]] = {
    "unknown": [
        ({"temp", "venom"}, "temperature_control_venom", 2.8),
        ({"wifi", "app"}, "app_connectivity", 2.8),
        ({"bluetooth", "pair"}, "app_connectivity", 2.8),
        ({"broken", "arrived"}, "damaged_on_arrival", 2.6),
        ({"missing", "part"}, "assembly", 2.5),
        ({"missing", "cover"}, "assembly", 2.7),
        ({"warranty", "replace"}, "warranty_replacement", 2.6),
        ({"tracking", "late"}, "shipping", 2.4),
        ({"ignite", "start"}, "ignition_startup", 2.4),
        ({"order", "confirmed"}, "order_admin", 2.7),
        ({"star", "review"}, "review_marketing", 2.9),
        ({"google", "review"}, "review_marketing", 2.9),
        ({"huntsman", "include"}, "product_question", 2.8),
        ({"weber", "kettle"}, "product_question", 2.8),
    ]
}
THEME_OWNER = {
    "shipping": "CX Operations",
    "damaged_on_arrival": "Quality",
    "temperature_control_venom": "Product / Firmware",
    "ignition_startup": "Product / Hardware",
    "app_connectivity": "App / Firmware",
    "assembly": "Product / Documentation",
    "warranty_replacement": "CX Operations",
    "order_admin": "CX Operations",
    "product_question": "Sales / CX",
    "review_marketing": "Marketing",
    "unknown": "Customer Experience",
}
THEME_IMPACT = {
    "shipping": {"impact_type": ["conversion", "support_burden"], "estimated_impact_level": "medium", "estimated_conversion_impact_pct": -2.5, "estimated_aov_impact_pct": -0.5, "recommended_action": "Audit carriers, tracking workflow, and SLA exceptions.", "urgency": "medium", "expected_metric_affected": "conversion"},
    "damaged_on_arrival": {"impact_type": ["aov", "support_burden"], "estimated_impact_level": "high", "estimated_conversion_impact_pct": -1.5, "estimated_aov_impact_pct": -3.5, "recommended_action": "Audit packaging, inbound damage, and final inspection.", "urgency": "high", "expected_metric_affected": "aov"},
    "temperature_control_venom": {"impact_type": ["conversion", "support_burden"], "estimated_impact_level": "high", "estimated_conversion_impact_pct": -4.0, "estimated_aov_impact_pct": -1.0, "recommended_action": "Investigate fan, probe, and temperature stability issues.", "urgency": "high", "expected_metric_affected": "conversion"},
    "ignition_startup": {"impact_type": ["conversion", "support_burden"], "estimated_impact_level": "high", "estimated_conversion_impact_pct": -3.2, "estimated_aov_impact_pct": -0.8, "recommended_action": "Review ignition reliability and startup hardware failures.", "urgency": "high", "expected_metric_affected": "conversion"},
    "app_connectivity": {"impact_type": ["conversion", "support_burden"], "estimated_impact_level": "medium", "estimated_conversion_impact_pct": -2.8, "estimated_aov_impact_pct": -0.6, "recommended_action": "Audit pairing reliability, app stability, and firmware handoff.", "urgency": "medium", "expected_metric_affected": "conversion"},
    "assembly": {"impact_type": ["conversion", "support_burden"], "estimated_impact_level": "medium", "estimated_conversion_impact_pct": -1.7, "estimated_aov_impact_pct": -0.4, "recommended_action": "Improve assembly instructions and missing-part resolution flow.", "urgency": "medium", "expected_metric_affected": "conversion"},
    "warranty_replacement": {"impact_type": ["aov", "support_burden"], "estimated_impact_level": "medium", "estimated_conversion_impact_pct": -1.2, "estimated_aov_impact_pct": -2.4, "recommended_action": "Tighten replacement workflows and root-cause repeat failures.", "urgency": "medium", "expected_metric_affected": "aov"},
    "order_admin": {"impact_type": ["support_burden"], "estimated_impact_level": "low", "estimated_conversion_impact_pct": -0.5, "estimated_aov_impact_pct": 0.0, "recommended_action": "Reduce manual order follow-ups through clearer transactional comms.", "urgency": "low", "expected_metric_affected": "support_burden"},
    "product_question": {"impact_type": ["conversion"], "estimated_impact_level": "low", "estimated_conversion_impact_pct": -0.8, "estimated_aov_impact_pct": 0.0, "recommended_action": "Clarify compatibility and product-fit messaging on site.", "urgency": "low", "expected_metric_affected": "conversion"},
    "review_marketing": {"impact_type": ["conversion"], "estimated_impact_level": "low", "estimated_conversion_impact_pct": -0.4, "estimated_aov_impact_pct": 0.0, "recommended_action": "Route review/marketing workflows out of support queue.", "urgency": "low", "expected_metric_affected": "conversion"},
    "unknown": {"impact_type": ["support_burden"], "estimated_impact_level": "low", "estimated_conversion_impact_pct": -0.3, "estimated_aov_impact_pct": 0.0, "recommended_action": "Review unknown bucket for additional taxonomy expansion.", "urgency": "low", "expected_metric_affected": "support_burden"},
}
PRODUCT_PATTERNS = {
    "venom": ["venom"],
    "huntsman": ["huntsman"],
    "weber kettle": ["weber", "kettle"],
    "spider grills": ["spider", "grill", "grills"],
}
SEVERITY_WEIGHT = {"high": 1.5, "medium": 1.0, "low": 0.6}
IMPACT_WEIGHT = {"conversion": 1.5, "aov": 1.3, "support_burden": 1.0}
LIVE_SOURCES = ["freshdesk", "aws_telemetry"]
SCAFFOLDED_SOURCES = ["reddit", "discord", "facebook", "google_reviews", "reviews"]
UNKNOWN_CONFIDENCE_THRESHOLD = 0.4


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def _normalize_text(ticket: FreshdeskTicket) -> dict[str, str]:
    subject = (ticket.subject or "").lower()
    raw = ticket.raw_payload or {}
    description = str(raw.get("description_text") or raw.get("description") or "").lower()
    tags = " ".join(ticket.tags_json or []).lower()
    combined = f"{subject} {description} {tags}".strip()
    return {"subject": subject, "description": description, "tags": tags, "combined": combined}


def _theme_score(parts: dict[str, str], terms: list[str], theme_name: str) -> float:
    score = 0.0
    combined = parts["combined"]
    subject = parts["subject"]
    tags = parts["tags"]
    tokens = Counter(_tokenize(combined))
    keyword_hits = 0
    for term in terms:
        normalized_term = term.lower()
        if " " in normalized_term:
            if normalized_term in combined:
                score += 2.8
                keyword_hits += 1
            if normalized_term in subject:
                score += 1.7
            if normalized_term in tags:
                score += 1.7
        else:
            token_hits = tokens.get(normalized_term, 0)
            if token_hits:
                keyword_hits += token_hits
            score += token_hits * 1.0
            if normalized_term in subject:
                score += 1.5
            if normalized_term in tags:
                score += 1.2
    density_bonus = min(1.5, keyword_hits / max(len(tokens), 1) * 10.0)
    score += density_bonus
    for negative_term in NEGATIVE_THEME_TERMS.get(theme_name, []):
        if negative_term in combined:
            score -= 1.5
    return max(score, 0.0)


def _second_pass_inference(parts: dict[str, str], scores: dict[str, float]) -> tuple[str, float, list[str]] | None:
    tokens = set(_tokenize(parts["combined"]))
    secondaries: list[str] = []
    for required_tokens, inferred_theme, boost in CO_OCCURRENCE_HINTS.get("unknown", []):
        if required_tokens.issubset(tokens):
            scores[inferred_theme] = scores.get(inferred_theme, 0.0) + boost
    if not scores:
        return None
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_theme, top_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    gap = top_score - second_score
    total_score = sum(score for _, score in ranked)
    density = top_score / max(total_score, 1.0)
    confidence = round(min(0.99, 0.45 * density + 0.55 * min(1.0, gap / max(top_score, 1.0))), 2)
    secondaries = [theme for theme, score in ranked[1:3] if score > 0]
    if confidence < UNKNOWN_CONFIDENCE_THRESHOLD:
        return None
    return top_theme, confidence, secondaries


def _mine_unknown_variants(parts: dict[str, str]) -> list[str]:
    tokens = [token for token in _tokenize(parts["combined"]) if len(token) > 4]
    counts = Counter(tokens)
    return [token for token, _ in counts.most_common(5)]


def _classify_theme(parts: dict[str, str]) -> tuple[str, float, list[str], list[str]]:
    scored: dict[str, float] = {}
    for theme, terms in THEMES.items():
        score = _theme_score(parts, terms, theme)
        if score > 0:
            scored[theme] = score
    if not scored:
        inferred = _second_pass_inference(parts, scored)
        if inferred is None:
            return "unknown", 0.0, [], _mine_unknown_variants(parts)
        theme, confidence, secondaries = inferred
        return theme, confidence, secondaries, []

    ranked = sorted(scored.items(), key=lambda item: item[1], reverse=True)
    top_theme, top_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    gap = top_score - second_score
    total_score = sum(score for _, score in ranked)
    density = top_score / max(total_score, 1.0)
    confidence = round(min(0.99, 0.45 * density + 0.55 * min(1.0, gap / max(top_score, 1.0))), 2)
    secondaries = [theme for theme, score in ranked[1:3] if score > 0]
    if confidence < UNKNOWN_CONFIDENCE_THRESHOLD:
        inferred = _second_pass_inference(parts, scored)
        if inferred is not None:
            theme, confidence, secondaries = inferred
            return theme, confidence, secondaries, []
        return "unknown", confidence, secondaries, _mine_unknown_variants(parts)
    return top_theme, confidence, secondaries, []


def _infer_product(text: str) -> str | None:
    for product, terms in PRODUCT_PATTERNS.items():
        if all(term in text for term in terms) if len(terms) > 1 else any(term in text for term in terms):
            return product
    return None


def _severity(ticket: FreshdeskTicket, theme: str) -> str:
    priority = str(ticket.priority or "").lower()
    if priority in {"4", "urgent", "high"}:
        return "high"
    # Only auto-escalate product safety themes (damaged/ignition), not temperature
    # which can include normal questions about temp settings during preheat, etc.
    if theme in {"damaged_on_arrival", "ignition_startup"}:
        return "high"
    if theme == "temperature_control_venom" and priority in {"3", "medium"}:
        return "medium"
    if priority in {"3", "medium"}:
        return "medium"
    return "low"


def _priority_score(severity: str, impact_types: list[str], tickets_per_100_orders: float | None) -> float:
    if tickets_per_100_orders is None:
        return 0.0
    severity_weight = SEVERITY_WEIGHT.get(severity, 1.0)
    impact_weight = max(IMPACT_WEIGHT.get(impact, 1.0) for impact in impact_types) if impact_types else 1.0
    return round(tickets_per_100_orders * severity_weight * impact_weight, 2)


def _priority_reason_summary(payload: dict[str, Any]) -> str:
    burden = payload.get("tickets_per_100_orders_by_theme")
    trend = payload.get("trend_label")
    impact_type = payload.get("impact_type", [])
    severity = payload.get("severity")
    impact_desc = "/".join(impact_type) if impact_type else "support_burden"
    return (
        f"{severity.capitalize()} priority because complaint burden is "
        f"{round(burden, 2) if burden is not None else 'n/a'} per 100 orders and impact is {impact_desc}-related, "
        f"while short-term trend is {trend}."
    )


def get_cluster_ticket_detail(db: Session, theme: str, lookback_days: int = 30) -> dict[str, Any]:
    """Return ticket-level detail for a given issue theme.

    Re-classifies tickets to find those matching the theme, then returns:
    - Individual ticket summaries (subject, status, priority, dates)
    - Unique customer (requester_id) count
    - Sub-topic groupings by keyword analysis of subjects
    - Adjusted severity based on unique customer ratio
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    tickets = db.execute(
        select(FreshdeskTicket).where(FreshdeskTicket.created_at_source >= cutoff)
    ).scalars().all()

    matched_tickets: list[dict[str, Any]] = []
    requester_ids: set[str] = set()
    subject_tokens: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    priority_counts: Counter[str] = Counter()
    channel_counts: Counter[str] = Counter()

    for ticket in tickets:
        parts = _normalize_text(ticket)
        classified_theme, confidence, secondaries, _ = _classify_theme(parts)
        if classified_theme != theme:
            continue

        req_id = ticket.requester_id or "unknown"
        requester_ids.add(req_id)
        status_counts[ticket.status or "unknown"] += 1
        priority_counts[str(ticket.priority or "unknown")] += 1
        channel_counts[ticket.channel or "unknown"] += 1

        # Extract meaningful subject tokens for sub-topic clustering
        tokens = [t for t in _tokenize(ticket.subject or "") if len(t) > 3]
        subject_tokens.update(tokens)

        matched_tickets.append({
            "ticket_id": ticket.ticket_id,
            "subject": ticket.subject,
            "status": ticket.status,
            "priority": ticket.priority,
            "channel": ticket.channel,
            "requester_id": req_id,
            "created_at": ticket.created_at_source.isoformat() if ticket.created_at_source else None,
            "updated_at": ticket.updated_at_source.isoformat() if ticket.updated_at_source else None,
            "resolved_at": ticket.resolved_at_source.isoformat() if ticket.resolved_at_source else None,
            "first_response_hours": ticket.first_response_hours,
            "resolution_hours": ticket.resolution_hours,
            "confidence": confidence,
            "tags": ticket.tags_json or [],
        })

    total_tickets = len(matched_tickets)
    unique_customers = len(requester_ids)

    # Build sub-topic clusters from common subject keywords
    # Remove theme keywords and common stop words to find distinguishing topics
    theme_terms_set = set()
    for term in THEMES.get(theme, []):
        theme_terms_set.update(term.lower().split())
    stop_words = {"the", "and", "for", "that", "this", "with", "not", "from", "have", "been", "about", "your", "will", "just", "when", "what", "they", "need", "help", "please", "issue", "problem", "spider", "grills", "grill"}
    filtered_tokens = {t: c for t, c in subject_tokens.items() if t not in theme_terms_set and t not in stop_words and c >= 2}
    sub_topics = [{"keyword": token, "count": count} for token, count in sorted(filtered_tokens.items(), key=lambda x: x[1], reverse=True)[:15]]

    # Adjusted severity: if most tickets come from very few customers, lower severity
    customer_ratio = unique_customers / max(total_tickets, 1)
    if total_tickets >= 5 and customer_ratio < 0.2:
        severity_adjustment = "downgraded"
        severity_reason = f"Only {unique_customers} unique customer(s) filed {total_tickets} tickets — likely repeat reporter(s), not widespread issue."
    elif total_tickets >= 10 and customer_ratio > 0.8:
        severity_adjustment = "upgraded"
        severity_reason = f"{unique_customers} unique customers out of {total_tickets} tickets — broad impact across customer base."
    else:
        severity_adjustment = "unchanged"
        severity_reason = f"{unique_customers} unique customers across {total_tickets} tickets."

    # Requester frequency breakdown
    req_counts: Counter[str] = Counter()
    for t in matched_tickets:
        req_counts[t["requester_id"]] += 1
    top_requesters = [{"requester_id": rid, "ticket_count": cnt} for rid, cnt in req_counts.most_common(10)]

    return {
        "theme": theme,
        "theme_title": theme.replace("_", " ").title(),
        "total_tickets": total_tickets,
        "unique_customers": unique_customers,
        "customer_ratio": round(customer_ratio, 3),
        "severity_adjustment": severity_adjustment,
        "severity_reason": severity_reason,
        "status_breakdown": dict(status_counts),
        "priority_breakdown": dict(priority_counts),
        "channel_breakdown": dict(channel_counts),
        "sub_topics": sub_topics,
        "top_requesters": top_requesters,
        "tickets": sorted(matched_tickets, key=lambda t: t["created_at"] or "", reverse=True),
        "owner_team": THEME_OWNER.get(theme, "Customer Experience"),
        "impact": THEME_IMPACT.get(theme, THEME_IMPACT["unknown"]),
    }


def build_issue_radar(db: Session, lookback_days: int = 30) -> dict[str, Any]:
    upsert_source_config(db, "freshdesk", configured=True, sync_mode="poll", config_json={"source_type": "connector", "issue_radar_live": True})
    telemetry_ready = telemetry_tables_available(db)
    telemetry_sessions_exist = telemetry_ready and (db.execute(select(TelemetrySession.id).limit(1)).first() is not None)
    upsert_source_config(db, "aws_telemetry", configured=telemetry_sessions_exist, sync_mode="pull", config_json={"source_type": "connector", "issue_radar_live": telemetry_sessions_exist})
    for source in SCAFFOLDED_SOURCES:
        upsert_source_config(db, source, configured=False, enabled=False, sync_mode="stub", config_json={"source_type": "connector", "issue_radar_live": False})
    db.commit()

    # Preserve Slack + ClickUp signals across rebuilds — they're produced by
    # their own connectors' scanners (keyed on message_ts / task_id
    # respectively) and are already idempotent. They also feed the DECI
    # auto-draft engine, so wiping them would orphan open drafts.
    db.execute(delete(IssueSignal).where(IssueSignal.source.notin_(["slack", "clickup"])))
    db.execute(delete(IssueCluster))

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    tickets = db.execute(
        select(FreshdeskTicket).where(FreshdeskTicket.created_at_source >= cutoff)
    ).scalars().all()
    orders_by_day = {
        str(row.business_date): row.orders
        for row in db.execute(select(ShopifyOrderDaily).where(ShopifyOrderDaily.business_date >= cutoff.date())).scalars().all()
    }

    theme_ticket_counts: dict[str, int] = defaultdict(int)
    theme_high_counts: dict[str, int] = defaultdict(int)
    theme_products: dict[str, set[str]] = defaultdict(set)
    theme_confidence: dict[str, list[float]] = defaultdict(list)
    theme_secondaries: dict[str, Counter[str]] = defaultdict(Counter)
    daily_theme_counts: dict[tuple[str, str], int] = defaultdict(int)
    unknown_phrase_variants: Counter[str] = Counter()
    moved_examples: list[dict[str, Any]] = []

    before_unknown = len(tickets)
    after_unknown = 0

    for ticket in tickets:
        parts = _normalize_text(ticket)
        theme, class_confidence, secondaries, mined_variants = _classify_theme(parts)
        if theme == "unknown":
            after_unknown += 1
            unknown_phrase_variants.update(mined_variants)
        elif len(moved_examples) < 12 and any(token in parts["combined"] for token in ["huntsman", "review", "cover", "confirmed", "weber", "venom"]):
            moved_examples.append({
                "ticket_id": ticket.ticket_id,
                "subject": ticket.subject,
                "theme": theme,
                "confidence": class_confidence,
                "secondary_themes": secondaries,
            })
        severity = _severity(ticket, theme)
        product = _infer_product(parts["combined"])
        business_date = (
            ticket.created_at_source.astimezone(BUSINESS_TZ).date()
            if ticket.created_at_source else None
        )
        if business_date is None:
            continue
        date_key = str(business_date)
        daily_theme_counts[(date_key, theme)] += 1
        theme_ticket_counts[theme] += 1
        theme_confidence[theme].append(class_confidence)
        theme_secondaries[theme].update(secondaries)
        if severity == "high":
            theme_high_counts[theme] += 1
        if product:
            theme_products[theme].add(product)

    theme_daily_series: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (business_date, theme), count in sorted(daily_theme_counts.items()):
        orders = orders_by_day.get(business_date, 0)
        per_100_orders = (count / orders * 100.0) if orders else None
        theme_daily_series[theme].append({
            "business_date": business_date,
            "count": count,
            "tickets_per_100_orders": round(per_100_orders, 2) if per_100_orders is not None else None,
        })

    cluster_payloads: list[dict[str, Any]] = []
    for theme, total_count in sorted(theme_ticket_counts.items(), key=lambda item: item[1], reverse=True):
        series = theme_daily_series.get(theme, [])
        recent = sum(point["count"] for point in series[-7:]) if series else 0
        prior = sum(point["count"] for point in series[-14:-7]) if len(series) >= 14 else 0
        trend_pct = (((recent - prior) / prior) * 100.0) if prior else (100.0 if recent > 0 else 0.0)
        severity = "high" if theme_high_counts[theme] >= max(2, total_count * 0.25) else "medium" if total_count >= 3 else "low"
        confidence = round(sum(theme_confidence[theme]) / max(len(theme_confidence[theme]), 1), 2)
        owner = THEME_OWNER.get(theme, "Customer Experience")
        affected_products = sorted(theme_products.get(theme, set()))
        impact_meta = THEME_IMPACT.get(theme, THEME_IMPACT["unknown"])

        period_orders = sum(orders_by_day.get(point["business_date"], 0) for point in series)
        tickets_per_100_orders = (total_count / period_orders * 100.0) if period_orders else None
        priority_score = _priority_score(severity, impact_meta["impact_type"], tickets_per_100_orders)
        if trend_pct > 25:
            trend_label = "rising"
        elif trend_pct < -25:
            trend_label = "declining"
        else:
            trend_label = "stable"

        payload = {
            "theme": theme,
            "title": theme.replace("_", " ").title(),
            "severity": severity,
            "confidence": confidence,
            "owner_team": owner,
            "total_tickets": total_count,
            "recent_7d": recent,
            "prior_7d": prior,
            "trend_pct": round(trend_pct, 2),
            "trend_label": trend_label,
            "affected_products": affected_products,
            "secondary_themes": [name for name, _ in theme_secondaries[theme].most_common(3)],
            "daily_series": series,
            "tickets_per_100_orders_by_theme": round(tickets_per_100_orders, 2) if tickets_per_100_orders is not None else None,
            "impact_type": impact_meta["impact_type"],
            "estimated_impact_level": impact_meta["estimated_impact_level"],
            "estimated_conversion_impact_pct": impact_meta["estimated_conversion_impact_pct"],
            "estimated_aov_impact_pct": impact_meta["estimated_aov_impact_pct"],
            "recommended_action": impact_meta["recommended_action"],
            "urgency": impact_meta["urgency"],
            "expected_metric_affected": impact_meta["expected_metric_affected"],
            "priority_score": priority_score,
        }
        payload["priority_reason_summary"] = _priority_reason_summary(payload)
        cluster_payloads.append(payload)

    cluster_payloads.sort(key=lambda item: item["priority_score"], reverse=True)

    clusters: list[IssueCluster] = []
    signals: list[IssueSignal] = []
    for idx, payload in enumerate(cluster_payloads, start=1):
        payload["priority_rank"] = idx
        cluster = IssueCluster(
            cluster_key=f"freshdesk:{payload['theme']}",
            title=payload["title"],
            source_count=1,
            severity=payload["severity"],
            confidence=payload["confidence"],
            owner_team=payload["owner_team"],
            status="open",
            details_json={
                "theme": payload["theme"],
                "source": "freshdesk",
                "total_tickets": payload["total_tickets"],
                "recent_7d": payload["recent_7d"],
                "prior_7d": payload["prior_7d"],
                "trend_pct": payload["trend_pct"],
                "trend_label": payload["trend_label"],
                "affected_products": payload["affected_products"],
                "secondary_themes": payload["secondary_themes"],
                "daily_series": payload["daily_series"],
                "tickets_per_100_orders_by_theme": payload["tickets_per_100_orders_by_theme"],
                "impact_type": payload["impact_type"],
                "estimated_impact_level": payload["estimated_impact_level"],
                "estimated_conversion_impact_pct": payload["estimated_conversion_impact_pct"],
                "estimated_aov_impact_pct": payload["estimated_aov_impact_pct"],
                "recommended_action": payload["recommended_action"],
                "urgency": payload["urgency"],
                "expected_metric_affected": payload["expected_metric_affected"],
                "priority_score": payload["priority_score"],
                "priority_rank": payload["priority_rank"],
                "priority_reason_summary": payload["priority_reason_summary"],
            },
        )
        db.add(cluster)
        clusters.append(cluster)

        signal_type = f"{payload['trend_label']}_theme"
        title_prefix = payload["trend_label"].capitalize()
        summary = (
            f"{payload['title']} complaints are {payload['trend_label']} with {payload['recent_7d']} tickets in the last 7 days "
            f"({round(payload['trend_pct'], 1)}% vs prior period, {payload['tickets_per_100_orders_by_theme'] if payload['tickets_per_100_orders_by_theme'] is not None else 'n/a'} tickets per 100 orders, priority score {payload['priority_score']})."
        )
        if payload["recent_7d"] >= 2:
            signal = IssueSignal(
                business_date=datetime.now(BUSINESS_TZ).date(),
                signal_type=signal_type,
                severity=payload["severity"],
                confidence=payload["confidence"],
                source="freshdesk",
                title=f"{title_prefix} issue: {payload['title']}",
                summary=summary,
                metadata_json={
                    "theme": payload["theme"],
                    "trend_pct": payload["trend_pct"],
                    "trend_label": payload["trend_label"],
                    "recent_7d": payload["recent_7d"],
                    "prior_7d": payload["prior_7d"],
                    "affected_products": payload["affected_products"],
                    "secondary_themes": payload["secondary_themes"],
                    "tickets_per_100_orders": payload["tickets_per_100_orders_by_theme"],
                    "impact_type": payload["impact_type"],
                    "estimated_impact_level": payload["estimated_impact_level"],
                    "estimated_conversion_impact_pct": payload["estimated_conversion_impact_pct"],
                    "estimated_aov_impact_pct": payload["estimated_aov_impact_pct"],
                    "recommended_action": payload["recommended_action"],
                    "urgency": payload["urgency"],
                    "expected_metric_affected": payload["expected_metric_affected"],
                    "priority_score": payload["priority_score"],
                    "priority_rank": payload["priority_rank"],
                    "priority_reason_summary": payload["priority_reason_summary"],
                },
            )
            db.add(signal)
            signals.append(signal)

    db.commit()

    telemetry_daily_rows = db.execute(select(TelemetryDaily).order_by(TelemetryDaily.business_date)).scalars().all() if telemetry_ready else []
    telemetry_sessions = db.execute(select(TelemetrySession)).scalars().all() if telemetry_ready else []
    if telemetry_daily_rows and telemetry_sessions:
        latest = telemetry_daily_rows[-1]

        # --- Historical comparison for temperature stability ---
        # Compare latest stability against 30-day and 7-day averages to detect
        # actual degradation vs. normal operating range.
        stability_history = [row.temp_stability_score for row in telemetry_daily_rows if row.temp_stability_score is not None]
        stability_30d_avg = round(sum(stability_history[-30:]) / max(len(stability_history[-30:]), 1), 4) if stability_history else 0.0
        stability_7d_avg = round(sum(stability_history[-7:]) / max(len(stability_history[-7:]), 1), 4) if stability_history else 0.0
        stability_degraded = latest.temp_stability_score < stability_30d_avg - 0.05  # degraded = dropped >5pp from historical avg

        # --- Cross-reference temperature telemetry with Freshdesk ticket volume ---
        # Only flag temperature as an elevated issue if support tickets corroborate.
        temp_ticket_cluster = next(
            (c for c in clusters if (c.details_json or {}).get("theme") == "temperature_control_venom"),
            None,
        )
        temp_ticket_count_7d = (temp_ticket_cluster.details_json or {}).get("recent_7d", 0) if temp_ticket_cluster else 0
        temp_tickets_rising = temp_ticket_cluster and (temp_ticket_cluster.details_json or {}).get("trend_label") == "rising"

        rising_disconnects = latest.disconnect_rate >= 0.12
        # Temperature instability: must be below threshold AND either degraded vs history OR corroborated by tickets
        unstable_temp = latest.temp_stability_score <= 0.72 and (stability_degraded or temp_ticket_count_7d >= 3)
        high_override = latest.manual_override_rate >= 0.18
        if rising_disconnects or unstable_temp or high_override:
            if rising_disconnects and unstable_temp:
                telemetry_theme = "telemetry_reliability"
                telemetry_title = "Telemetry Reliability Drop"
                telemetry_summary = "Disconnect rate and temperature stability both indicate a product reliability issue."
            elif rising_disconnects:
                telemetry_theme = "disconnect_cluster"
                telemetry_title = "Disconnect Cluster"
                telemetry_summary = "Disconnect rate is elevated across recent connected sessions."
            elif unstable_temp:
                telemetry_theme = "temp_instability"
                telemetry_title = "Temperature Instability (Post-Target)"
                corroboration = f" Corroborated by {temp_ticket_count_7d} support tickets in 7d." if temp_ticket_count_7d >= 3 else ""
                degradation = f" Score degraded {round((stability_30d_avg - latest.temp_stability_score) * 100, 1)}pp from 30d avg." if stability_degraded else ""
                telemetry_summary = f"Post-target temperature stability score ({round(latest.temp_stability_score, 2)}) is below threshold after filtering preheat data.{degradation}{corroboration}"
            else:
                telemetry_theme = "manual_override_spike"
                telemetry_title = "Manual Override Spike"
                telemetry_summary = "Manual override rate is elevated, suggesting the product is not holding course automatically."

            firmware_counter = Counter((row.firmware_version or "unknown") for row in telemetry_sessions)
            grill_counter = Counter((row.grill_type or "unknown") for row in telemetry_sessions)

            # Priority score: temperature only escalates if corroborated by tickets or historical degradation
            temp_priority = (1 - latest.temp_stability_score) * 100 * 1.8
            if unstable_temp and temp_tickets_rising:
                temp_priority *= 1.3  # boost when both telemetry + tickets agree
            elif unstable_temp and not stability_degraded:
                temp_priority *= 0.6  # dampen if within historical norms

            telemetry_details = {
                "theme": telemetry_theme,
                "source": "aws_telemetry",
                "truth_state": "estimated",
                "confidence_caveat": "Stability scores reflect post-target holding performance only (preheat excluded). Telemetry reflects only the observed bounded DynamoDB slice, not full-fleet canonical completeness.",
                "evidence": [
                    f"disconnect_rate={round(latest.disconnect_rate, 4)}",
                    f"temp_stability_score={round(latest.temp_stability_score, 4)} (post-target)",
                    f"stability_30d_avg={stability_30d_avg}",
                    f"stability_7d_avg={stability_7d_avg}",
                    f"stability_degraded={stability_degraded}",
                    f"temp_tickets_7d={temp_ticket_count_7d}",
                    f"temp_tickets_rising={temp_tickets_rising}",
                    f"manual_override_rate={round(latest.manual_override_rate, 4)}",
                    f"firmware_health_score={round(latest.firmware_health_score, 4)}",
                    f"session_reliability_score={round(latest.session_reliability_score, 4)}",
                ],
                "owner": "Kyle",
                "disconnect_rate": round(latest.disconnect_rate, 4),
                "temp_stability_score": round(latest.temp_stability_score, 4),
                "stability_30d_avg": stability_30d_avg,
                "stability_7d_avg": stability_7d_avg,
                "stability_degraded": stability_degraded,
                "temp_ticket_count_7d": temp_ticket_count_7d,
                "temp_tickets_rising": bool(temp_tickets_rising),
                "manual_override_rate": round(latest.manual_override_rate, 4),
                "firmware_health_score": round(latest.firmware_health_score, 4),
                "session_reliability_score": round(latest.session_reliability_score, 4),
                "affected_firmware_versions": [name for name, _ in firmware_counter.most_common(5)],
                "affected_grill_types": [name for name, _ in grill_counter.most_common(5)],
                "recommended_action": "Slice failures by firmware and grill type, then prioritize the dominant failure cohort. Cross-reference with Freshdesk temperature complaints to isolate root cause.",
                "priority_reason_summary": telemetry_summary,
                "priority_score": round(max(latest.disconnect_rate * 100 * 2.2, temp_priority, latest.manual_override_rate * 100 * 1.6), 2),
                "trend_label": "rising" if stability_degraded or temp_tickets_rising else "stable",
                "impact_type": ["support_burden", "conversion"],
            }
            # Severity: require BOTH telemetry anomaly AND ticket corroboration for "high"
            telemetry_severity = "medium"
            if latest.disconnect_rate >= 0.18:
                telemetry_severity = "high"
            elif latest.temp_stability_score <= 0.65 and temp_ticket_count_7d >= 3:
                telemetry_severity = "high"  # genuinely bad stability + tickets confirm
            elif latest.temp_stability_score <= 0.70 and temp_tickets_rising:
                telemetry_severity = "high"  # bad stability + rising ticket trend

            telemetry_cluster = IssueCluster(
                cluster_key=f"aws_telemetry:{telemetry_theme}",
                title=telemetry_title,
                source_count=1,
                severity=telemetry_severity,
                confidence=0.82,
                owner_team="Product / Firmware",
                status="open",
                details_json=telemetry_details,
            )
            db.add(telemetry_cluster)
            db.flush()
            clusters.append(telemetry_cluster)
            telemetry_signal = IssueSignal(
                business_date=datetime.now(BUSINESS_TZ).date(),
                signal_type="telemetry_issue",
                severity=telemetry_cluster.severity,
                confidence=0.82,
                source="aws_telemetry",
                title=f"Telemetry issue: {telemetry_title}",
                summary=telemetry_summary,
                metadata_json=telemetry_details,
            )
            db.add(telemetry_signal)
            db.flush()
            signals.append(telemetry_signal)

    highest_business_risk = sorted(
        [
            {
                "id": cluster.id,
                "title": cluster.title,
                "severity": cluster.severity,
                "confidence": cluster.confidence,
                "owner_team": cluster.owner_team,
                "details_json": cluster.details_json,
            }
            for cluster in clusters
        ],
        key=lambda item: item["details_json"].get("priority_score", 0),
        reverse=True,
    )
    highest_burden = sorted(
        highest_business_risk,
        key=lambda item: item["details_json"].get("tickets_per_100_orders_by_theme", 0) or 0,
        reverse=True,
    )
    fastest_rising = sorted(
        highest_business_risk,
        key=lambda item: item["details_json"].get("trend_pct", 0),
        reverse=True,
    )

    db.commit()

    source_breakdown = [{"source": "freshdesk", "live": True, "signals": len([s for s in signals if s.source == 'freshdesk']), "clusters": len([c for c in clusters if str(c.cluster_key).startswith('freshdesk:')])}]
    source_breakdown.append({"source": "aws_telemetry", "live": telemetry_sessions_exist, "signals": len([s for s in signals if s.source == 'aws_telemetry']), "clusters": len([c for c in clusters if str(c.cluster_key).startswith('aws_telemetry:')])})
    source_breakdown.extend({"source": source, "live": False, "signals": 0, "clusters": 0} for source in SCAFFOLDED_SOURCES)
    trend_heatmap = [
        {"theme": payload["theme"], "points": payload["daily_series"]}
        for payload in cluster_payloads
    ]

    return {
        "signals": [
            {
                "id": signal.id,
                "title": signal.title,
                "summary": signal.summary,
                "severity": signal.severity,
                "confidence": signal.confidence,
                "source": signal.source,
                "metadata_json": signal.metadata_json,
            }
            for signal in signals
        ],
        "clusters": highest_business_risk,
        "highest_business_risk": highest_business_risk[:10],
        "highest_burden": highest_burden[:10],
        "fastest_rising": fastest_rising[:10],
        "source_breakdown": source_breakdown,
        "trend_heatmap": trend_heatmap,
        "live_sources": LIVE_SOURCES,
        "scaffolded_sources": SCAFFOLDED_SOURCES,
        "classification_report": {
            "before_unknown_share": round(before_unknown / max(len(tickets), 1), 4),
            "after_unknown_share": round(after_unknown / max(len(tickets), 1), 4),
            "unknown_reduction_pct": round(((before_unknown - after_unknown) / max(before_unknown, 1)) * 100.0, 2),
            "top_unknown_variants": [token for token, _ in unknown_phrase_variants.most_common(20)],
            "moved_examples": moved_examples,
        },
    }


def read_cached_issue_radar(db: Session) -> dict[str, Any] | None:
    """Return the last-computed issue radar payload reconstructed from
    ``issue_clusters`` / ``issue_signals`` rows, without re-classifying
    tickets. Returns ``None`` if the cache is empty (caller should fall
    back to build_issue_radar once to warm it).

    The ticket-level classifier artifacts (``moved_examples``,
    ``top_unknown_variants``) are not persisted, so the returned
    ``classification_report`` contains empty placeholders. Every other
    field that the dashboard consumes is reconstructed from the stored
    cluster/signal rows.
    """
    clusters_rows = db.execute(select(IssueCluster)).scalars().all()
    if not clusters_rows:
        return None

    signals_rows = db.execute(select(IssueSignal)).scalars().all()

    clusters = [
        {
            "id": cluster.id,
            "title": cluster.title,
            "severity": cluster.severity,
            "confidence": cluster.confidence,
            "owner_team": cluster.owner_team,
            "details_json": cluster.details_json or {},
        }
        for cluster in clusters_rows
    ]
    highest_business_risk = sorted(
        clusters,
        key=lambda item: item["details_json"].get("priority_score", 0),
        reverse=True,
    )
    highest_burden = sorted(
        clusters,
        key=lambda item: item["details_json"].get("tickets_per_100_orders_by_theme", 0) or 0,
        reverse=True,
    )
    fastest_rising = sorted(
        clusters,
        key=lambda item: item["details_json"].get("trend_pct", 0),
        reverse=True,
    )

    signals = [
        {
            "id": signal.id,
            "title": signal.title,
            "summary": signal.summary,
            "severity": signal.severity,
            "confidence": signal.confidence,
            "source": signal.source,
            "metadata_json": signal.metadata_json,
        }
        for signal in signals_rows
    ]

    freshdesk_signal_count = sum(1 for s in signals_rows if s.source == "freshdesk")
    freshdesk_cluster_count = sum(1 for c in clusters_rows if str(c.cluster_key).startswith("freshdesk:"))
    telemetry_signal_count = sum(1 for s in signals_rows if s.source == "aws_telemetry")
    telemetry_cluster_count = sum(1 for c in clusters_rows if str(c.cluster_key).startswith("aws_telemetry:"))
    source_breakdown = [
        {"source": "freshdesk", "live": True, "signals": freshdesk_signal_count, "clusters": freshdesk_cluster_count},
        {"source": "aws_telemetry", "live": telemetry_cluster_count > 0, "signals": telemetry_signal_count, "clusters": telemetry_cluster_count},
    ]
    source_breakdown.extend({"source": source, "live": False, "signals": 0, "clusters": 0} for source in SCAFFOLDED_SOURCES)

    trend_heatmap = [
        {"theme": (c["details_json"].get("theme") or ""), "points": c["details_json"].get("daily_series", [])}
        for c in highest_business_risk
        if c["details_json"].get("theme")
    ]

    return {
        "signals": signals,
        "clusters": highest_business_risk,
        "highest_business_risk": highest_business_risk[:10],
        "highest_burden": highest_burden[:10],
        "fastest_rising": fastest_rising[:10],
        "source_breakdown": source_breakdown,
        "trend_heatmap": trend_heatmap,
        "live_sources": LIVE_SOURCES,
        "scaffolded_sources": SCAFFOLDED_SOURCES,
        "classification_report": {
            "before_unknown_share": 0.0,
            "after_unknown_share": 0.0,
            "unknown_reduction_pct": 0.0,
            "top_unknown_variants": [],
            "moved_examples": [],
        },
    }
