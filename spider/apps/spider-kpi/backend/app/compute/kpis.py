import logging
from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import (
    Alert,
    DriverDiagnostic,
    FreshdeskTicketsDaily,
    KPIDaily,
    KPIIntraday,
    Recommendation,
    ShopifyAnalyticsDaily,
    ShopifyAnalyticsIntraday,
    ShopifyOrderDaily,
    SourceSyncRun,
    TWSummaryDaily,
)
from app.services.issue_radar import build_issue_radar
from app.services.source_health import refresh_source_health_alerts, start_sync_run, finish_sync_run, upsert_source_config

logger = logging.getLogger(__name__)
VALIDATION_TOLERANCE = 0.01


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _relative_diff(expected: float, actual: float) -> float:
    if expected == 0:
        return 0.0 if actual == 0 else 1.0
    return abs(actual - expected) / abs(expected)


def _validation_warnings(record: KPIDaily, expected_conversion: float, expected_rps: float, expected_aov: float) -> list[str]:
    warnings: list[str] = []
    if _relative_diff(expected_conversion, record.conversion_rate) > VALIDATION_TOLERANCE:
        warnings.append(f"conversion_rate mismatch: expected {expected_conversion:.6f}, actual {record.conversion_rate:.6f}")
    if _relative_diff(expected_rps, record.revenue_per_session) > VALIDATION_TOLERANCE:
        warnings.append(f"revenue_per_session mismatch: expected {expected_rps:.6f}, actual {record.revenue_per_session:.6f}")
    if _relative_diff(expected_aov, record.average_order_value) > VALIDATION_TOLERANCE:
        warnings.append(f"average_order_value mismatch: expected {expected_aov:.6f}, actual {record.average_order_value:.6f}")
    return warnings


def _dynamic_driver_contributions(revenue_change: float, sessions_change: float, conversion_change: float, aov_change: float) -> list[dict]:
    raw = {
        "traffic": abs(sessions_change),
        "conversion": abs(conversion_change),
        "aov": abs(aov_change),
    }
    total = sum(raw.values()) or 1.0
    drivers = []
    for key, value in raw.items():
        normalized = value / total
        impact = revenue_change * normalized
        confidence = min(0.95, 0.45 + normalized * 0.5)
        drivers.append(
            {
                "type": key,
                "impact": round(impact, 2),
                "confidence": round(confidence, 2),
                "normalized_weight": round(normalized, 4),
            }
        )
    return sorted(drivers, key=lambda item: abs(item["impact"]), reverse=True)


def _data_quality_payload(metadata: dict | None) -> dict:
    metadata = metadata or {}
    return {
        "validation_warnings": metadata.get("validation_messages", []),
        "source_drift": metadata.get("reconciliation_messages", []),
        "missing_data": metadata.get("missing_data_messages", []),
    }


def recompute_daily_kpis(db: Session) -> int:
    existing_running = db.execute(
        select(SourceSyncRun)
        .where(SourceSyncRun.source_name == "decision-engine", SourceSyncRun.status == "running")
        .order_by(desc(SourceSyncRun.started_at))
        .limit(1)
    ).scalars().first()
    if existing_running is not None:
        logger.info("decision-engine compute skipped because a run is already active")
        return 0

    upsert_source_config(
        db,
        "decision-engine",
        configured=True,
        sync_mode="compute",
        config_json={"source_type": "compute"},
    )
    db.commit()
    compute_run = start_sync_run(db, "decision-engine", "recompute_daily_kpis", {})
    db.commit()

    shopify_rows = db.execute(select(ShopifyOrderDaily)).scalars().all()
    tw_map = {row.business_date: row for row in db.execute(select(TWSummaryDaily)).scalars().all()}
    shopify_analytics_map = {row.business_date: row for row in db.execute(select(ShopifyAnalyticsDaily)).scalars().all()}
    support_map = {row.business_date: row for row in db.execute(select(FreshdeskTicketsDaily)).scalars().all()}

    processed = 0
    validation_messages: list[dict] = []
    reconciliation_messages: list[dict] = []
    missing_data_messages: list[dict] = []

    for shopify in shopify_rows:
        tw = tw_map.get(shopify.business_date)
        shopify_analytics = shopify_analytics_map.get(shopify.business_date)
        support = support_map.get(shopify.business_date)

        revenue = shopify.revenue
        orders = shopify.orders
        sessions = shopify_analytics.sessions if shopify_analytics else 0.0
        if sessions == 0 and tw:
            sessions = tw.sessions
            missing_data_messages.append({
                "business_date": str(shopify.business_date),
                "type": "shopify_sessions_missing",
                "message": "Shopify sessions missing; falling back to Triple Whale sessions.",
            })
        ad_spend = tw.ad_spend if tw else 0.0
        purchases = tw.purchases if tw else float(orders)
        expected_conversion = _safe_div(float(orders), sessions) * 100.0
        expected_rps = _safe_div(revenue, sessions)
        expected_aov = _safe_div(revenue, float(orders))

        record = db.execute(
            select(KPIDaily).where(KPIDaily.business_date == shopify.business_date)
        ).scalars().first()
        if record is None:
            record = KPIDaily(business_date=shopify.business_date)
            db.add(record)

        record.revenue = revenue
        record.orders = orders
        record.average_order_value = expected_aov
        record.sessions = sessions
        record.conversion_rate = expected_conversion
        record.revenue_per_session = expected_rps
        record.add_to_cart_rate = tw.add_to_cart_rate if tw else (shopify_analytics.add_to_cart_rate if shopify_analytics else 0.0)
        record.bounce_rate = tw.bounce_rate if tw else (shopify_analytics.bounce_rate if shopify_analytics else 0.0)
        record.purchases = purchases
        record.ad_spend = ad_spend
        record.mer = _safe_div(revenue, ad_spend)
        record.cost_per_purchase = _safe_div(ad_spend, purchases)
        record.tickets_created = support.tickets_created if support else 0
        record.tickets_resolved = support.tickets_resolved if support else 0
        record.open_backlog = support.unresolved_tickets if support else 0
        record.first_response_time = support.first_response_hours if support else 0.0
        record.resolution_time = support.resolution_hours if support else 0.0
        record.sla_breach_rate = support.sla_breach_rate if support else 0.0
        record.csat = support.csat if support else 0.0
        reopen_count = support.reopened_tickets if support else 0
        record.reopen_rate = _safe_div(reopen_count * 100.0, support.tickets_created) if support and support.tickets_created else 0.0
        record.tickets_per_100_orders = _safe_div((support.tickets_created * 100.0), orders) if support and orders else 0.0
        processed += 1

        validation = _validation_warnings(record, expected_conversion, expected_rps, expected_aov)
        if validation:
            logger.warning("kpi validation mismatch", extra={"business_date": str(shopify.business_date), "warnings": validation})
            validation_messages.append({"business_date": str(shopify.business_date), "warnings": validation})

        if tw:
            purchase_drift = _relative_diff(float(orders), purchases) * 100.0
            sessions_drift = None
            if shopify_analytics and shopify_analytics.sessions:
                sessions_drift = _relative_diff(shopify_analytics.sessions, tw.sessions) * 100.0
            reconciliation = {
                "business_date": str(shopify.business_date),
                "orders_vs_purchases_pct_diff": round(purchase_drift, 2),
                "shopify_orders": orders,
                "tw_purchases": purchases,
                "tw_sessions": tw.sessions,
                "shopify_sessions": shopify_analytics.sessions if shopify_analytics else None,
                "sessions_pct_diff": round(sessions_drift, 2) if sessions_drift is not None else None,
            }
            reconciliation_messages.append(reconciliation)
            logger.info("source reconciliation", extra=reconciliation)

    intraday_bucket = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    shopify_intraday = db.execute(select(ShopifyAnalyticsIntraday).where(ShopifyAnalyticsIntraday.bucket_start == intraday_bucket)).scalars().first()
    if shopify_intraday is not None:
        intraday = db.execute(select(KPIIntraday).where(KPIIntraday.bucket_start == intraday_bucket)).scalars().first()
        if intraday is None:
            intraday = KPIIntraday(bucket_start=intraday_bucket)
            db.add(intraday)

        intraday_revenue = float(shopify_intraday.revenue or 0.0)
        intraday_sessions = float(shopify_intraday.sessions or 0.0)
        intraday_orders = 0
        intraday_aov = 0.0
        intraday_conversion = 0.0

        intraday.revenue = intraday_revenue
        intraday.sessions = intraday_sessions
        intraday.orders = intraday_orders
        intraday.average_order_value = intraday_aov
        intraday.conversion_rate = intraday_conversion

    compute_run.metadata_json = {
        "processed": processed,
        "validation_messages": validation_messages,
        "reconciliation_messages": reconciliation_messages,
        "missing_data_messages": missing_data_messages,
    }
    finish_sync_run(db, compute_run, status="success", records_processed=processed)
    db.commit()
    refresh_source_health_alerts(db)
    db.commit()
    return processed


def recompute_diagnostics(db: Session) -> None:
    rows = db.execute(select(KPIDaily).order_by(KPIDaily.business_date)).scalars().all()
    issue_payload = build_issue_radar(db)
    issue_clusters = issue_payload.get("clusters", [])
    db.query(Alert).delete()
    db.query(DriverDiagnostic).delete()
    db.query(Recommendation).delete()

    previous = None
    for row in rows:
        if previous is None:
            previous = row
            continue

        revenue_change = _safe_div((row.revenue - previous.revenue) * 100.0, previous.revenue) if previous.revenue else 0.0
        sessions_change = _safe_div((row.sessions - previous.sessions) * 100.0, previous.sessions) if previous.sessions else 0.0
        conversion_change = _safe_div((row.conversion_rate - previous.conversion_rate) * 100.0, previous.conversion_rate) if previous.conversion_rate else 0.0
        aov_change = _safe_div((row.average_order_value - previous.average_order_value) * 100.0, previous.average_order_value) if previous.average_order_value else 0.0

        drivers = _dynamic_driver_contributions(revenue_change, sessions_change, conversion_change, aov_change)
        primary_root_cause = f"{drivers[0]['type']}_drop" if revenue_change < 0 else f"{drivers[0]['type']}_lift"
        issue_link = None
        if conversion_change < -10.0:
            for cluster in issue_clusters:
                details = cluster.get("details_json", {})
                if details.get("trend_label") == "rising" and details.get("theme") == "temperature_control_venom":
                    issue_link = details
                    primary_root_cause = "temperature_control_venom"
                    break
        if aov_change < -10.0 and issue_link is None:
            for cluster in issue_clusters:
                details = cluster.get("details_json", {})
                if details.get("trend_label") == "rising" and details.get("theme") == "damaged_on_arrival":
                    issue_link = details
                    primary_root_cause = "damaged_on_arrival"
                    break

        data_completeness = 1.0 if row.sessions > 0 else 0.5
        top_two_share = abs(drivers[0]["impact"]) + abs(drivers[1]["impact"]) if len(drivers) > 1 else abs(drivers[0]["impact"])
        source_agreement = 0.9 if row.purchases in {0, float(row.orders)} else 0.7
        magnitude_consistency = min(1.0, abs(revenue_change) / max(top_two_share, 1.0))
        confidence = round(min(0.95, 0.35 * data_completeness + 0.3 * source_agreement + 0.35 * magnitude_consistency), 2)

        if revenue_change < -10.0:
            summary = f"Revenue changed {round(revenue_change, 1)}%. Weighted drivers indicate {drivers[0]['type']} had the largest contribution."
            owner_team = "Growth / UX" if drivers[0]["type"] == "conversion" else "Marketing" if drivers[0]["type"] == "traffic" else "Merchandising"
            recommendation = (
                "Investigate checkout friction, PDP clarity, and pricing presentation."
                if drivers[0]["type"] == "conversion"
                else "Audit paid traffic delivery and landing-page relevance."
                if drivers[0]["type"] == "traffic"
                else "Review bundling, pricing, and upsell placement."
            )
            if issue_link is not None:
                summary += f" Issue Radar also shows rising {issue_link.get('theme')} complaints with priority rank {issue_link.get('priority_rank')}."

            payload = {
                "revenue_change": round(revenue_change, 1),
                "drivers": drivers,
                "primary_root_cause": primary_root_cause,
                "sessions_change_pct": round(sessions_change, 1),
                "conversion_change_pct": round(conversion_change, 1),
                "aov_change_pct": round(aov_change, 1),
                "issue_link": issue_link,
                "confidence_components": {
                    "data_completeness": round(data_completeness, 2),
                    "source_agreement": round(source_agreement, 2),
                    "magnitude_consistency": round(magnitude_consistency, 2),
                },
            }

            db.add(
                Alert(
                    business_date=row.business_date,
                    source="decision-engine",
                    severity="high",
                    status="open",
                    title="Revenue decline detected",
                    message=summary,
                    owner_team=owner_team,
                    confidence=confidence,
                    metadata_json=payload,
                )
            )
            db.add(
                DriverDiagnostic(
                    business_date=row.business_date,
                    diagnostic_type="revenue_drop",
                    severity="high",
                    confidence=confidence,
                    owner_team=owner_team,
                    title="Revenue down",
                    summary=summary,
                    root_cause=primary_root_cause,
                    details_json=payload,
                )
            )
            db.add(
                Recommendation(
                    business_date=row.business_date,
                    owner_team=owner_team,
                    title="Priority action",
                    recommended_action=recommendation,
                    root_cause=primary_root_cause,
                    severity="high",
                    confidence=confidence,
                    estimated_impact="High revenue preservation and conversion recovery potential.",
                    metadata_json={"generated_at": datetime.now(timezone.utc).isoformat(), "drivers": drivers},
                )
            )

        if row.tickets_per_100_orders > 25:
            db.add(
                Alert(
                    business_date=row.business_date,
                    source="support",
                    severity="medium",
                    status="open",
                    title="Support burden elevated",
                    message="Support contacts are rising faster than order volume.",
                    owner_team="Customer Experience",
                    confidence=0.75,
                    metadata_json={"tickets_per_100_orders": round(row.tickets_per_100_orders, 2)},
                )
            )

        previous = row

    refresh_source_health_alerts(db)
    db.commit()


def get_data_quality(db: Session) -> dict:
    latest_run = db.execute(
        select(SourceSyncRun)
        .where(SourceSyncRun.source_name == "decision-engine", SourceSyncRun.status == "success")
        .order_by(desc(SourceSyncRun.started_at))
        .limit(1)
    ).scalars().first()
    return _data_quality_payload(latest_run.metadata_json if latest_run else {})
