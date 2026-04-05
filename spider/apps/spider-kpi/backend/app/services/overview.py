from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Alert, DriverDiagnostic, KPIDaily, Recommendation, ShopifyAnalyticsDaily, ShopifyOrderDaily, TWSummaryDaily
from app.services.source_health import get_source_health


def is_incomplete_kpi_day(row: KPIDaily | None) -> bool:
    if row is None:
        return False
    sessions = row.sessions or 0
    orders = row.orders or 0
    revenue = row.revenue or 0
    return sessions == 0 and (orders > 0 or revenue > 0)


def build_kpi_payload(
    row: KPIDaily,
    shopify_map: dict,
    shopify_analytics_map: dict,
    tw_map: dict,
) -> dict:
    shopify = shopify_map.get(row.business_date)
    shopify_analytics = shopify_analytics_map.get(row.business_date)
    tw = tw_map.get(row.business_date)

    if tw and (tw.sessions or 0) > 0:
        sessions_source = "triplewhale"
    elif shopify_analytics and (shopify_analytics.sessions or 0) > 0:
        sessions_source = "shopify_analytics"
    else:
        sessions_source = None

    revenue_source = "shopify" if shopify else ("triplewhale" if tw else None)
    payload = {
        "business_date": row.business_date,
        "revenue": row.revenue,
        "orders": row.orders,
        "average_order_value": row.average_order_value,
        "sessions": row.sessions,
        "conversion_rate": row.conversion_rate,
        "revenue_per_session": row.revenue_per_session,
        "add_to_cart_rate": row.add_to_cart_rate,
        "bounce_rate": row.bounce_rate,
        "purchases": row.purchases,
        "ad_spend": row.ad_spend,
        "mer": row.mer,
        "cost_per_purchase": row.cost_per_purchase,
        "tickets_created": row.tickets_created,
        "tickets_resolved": row.tickets_resolved,
        "open_backlog": row.open_backlog,
        "first_response_time": row.first_response_time,
        "resolution_time": row.resolution_time,
        "sla_breach_rate": row.sla_breach_rate,
        "csat": row.csat,
        "reopen_rate": row.reopen_rate,
        "tickets_per_100_orders": row.tickets_per_100_orders,
        "revenue_source": revenue_source,
        "sessions_source": sessions_source,
        "orders_source": "shopify" if shopify else None,
        "is_partial_day": (revenue_source != "shopify") or (sessions_source is None) or shopify is None,
        "is_fallback_day": revenue_source == "triplewhale" or sessions_source == "triplewhale",
    }
    return payload


def build_overview(db: Session) -> dict:
    kpis = db.execute(select(KPIDaily).order_by(KPIDaily.business_date)).scalars().all()
    shopify_map = {row.business_date: row for row in db.execute(select(ShopifyOrderDaily)).scalars().all()}
    shopify_analytics_map = {row.business_date: row for row in db.execute(select(ShopifyAnalyticsDaily)).scalars().all()}
    tw_map = {row.business_date: row for row in db.execute(select(TWSummaryDaily)).scalars().all()}
    alerts = db.execute(select(Alert).where(Alert.status == "open").order_by(desc(Alert.created_at)).limit(10)).scalars().all()
    diagnostics = db.execute(select(DriverDiagnostic).order_by(desc(DriverDiagnostic.business_date)).limit(10)).scalars().all()
    recommendations = db.execute(select(Recommendation).order_by(desc(Recommendation.created_at)).limit(10)).scalars().all()

    latest = None
    for row in reversed(kpis):
        payload = build_kpi_payload(row, shopify_map, shopify_analytics_map, tw_map)
        if not is_incomplete_kpi_day(row) and not payload["is_partial_day"]:
            latest = payload
            break
    if latest is None:
        for row in reversed(kpis):
            if not is_incomplete_kpi_day(row):
                latest = build_kpi_payload(row, shopify_map, shopify_analytics_map, tw_map)
                break
    return {
        "latest_kpi": latest,
        "daily_series": [build_kpi_payload(row, shopify_map, shopify_analytics_map, tw_map) for row in kpis],
        "alerts": alerts,
        "diagnostics": diagnostics,
        "recommendations": recommendations,
        "source_health": get_source_health(db),
    }
