from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import re
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import FreshdeskTicket, IssueCluster, IssueSignal, ShopifyOrderDaily
from app.services.source_health import upsert_source_config

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
LIVE_SOURCES = ["freshdesk"]
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
    if theme in {"damaged_on_arrival", "temperature_control_venom", "ignition_startup"}:
        return "high"
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


def build_issue_radar(db: Session, lookback_days: int = 30) -> dict[str, Any]:
    upsert_source_config(db, "freshdesk", configured=True, sync_mode="poll", config_json={"source_type": "connector", "issue_radar_live": True})
    for source in SCAFFOLDED_SOURCES:
        upsert_source_config(db, source, configured=False, enabled=False, sync_mode="stub", config_json={"source_type": "connector", "issue_radar_live": False})
    db.commit()

    db.execute(delete(IssueSignal))
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
        business_date = ticket.created_at_source.date() if ticket.created_at_source else None
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
                business_date=datetime.now(timezone.utc).date(),
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

    source_breakdown = [{"source": "freshdesk", "live": True, "signals": len(signals), "clusters": len(clusters)}]
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
