import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import KPIDaily, ShopifyOrderDaily, TWSummaryDaily
from app.services.source_health import upsert_source_config


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def seed_from_prototype_files(db: Session, base_dir: Path) -> dict[str, int]:
    processed_dir = base_dir / "data" / "processed"
    seeded = {"shopify_orders_daily": 0, "kpi_daily": 0, "tw_summary_daily": 0}
    shopify_seen = False
    kpi_seen = False
    tw_seen = False

    orders_daily = _load_json(processed_dir / "orders_daily.json", [])
    for row in orders_daily:
        shopify_seen = True
        business_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
        existing = db.execute(
            select(ShopifyOrderDaily).where(ShopifyOrderDaily.business_date == business_date)
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                ShopifyOrderDaily(
                    business_date=business_date,
                    orders=int(row.get("orders", 0)),
                    revenue=float(row.get("revenue", 0.0)),
                    average_order_value=(float(row.get("revenue", 0.0)) / int(row.get("orders", 1))) if int(row.get("orders", 0)) else 0.0,
                )
            )
            seeded["shopify_orders_daily"] += 1

    kpi_daily = _load_json(processed_dir / "kpi_daily.json", [])
    for row in kpi_daily:
        kpi_seen = True
        business_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
        existing = db.execute(
            select(KPIDaily).where(KPIDaily.business_date == business_date)
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                KPIDaily(
                    business_date=business_date,
                    revenue=float(row.get("revenue", 0.0)),
                    orders=int(row.get("orders", 0)),
                    average_order_value=float(row.get("aov", 0.0)),
                )
            )
            seeded["kpi_daily"] += 1

    tw = _load_json(processed_dir / "tw_metrics.json", {})
    if isinstance(tw, dict) and tw.get("date"):
        tw_seen = True
        business_date = datetime.strptime(tw["date"], "%Y-%m-%d").date()
        existing = db.execute(
            select(TWSummaryDaily).where(TWSummaryDaily.business_date == business_date)
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                TWSummaryDaily(
                    business_date=business_date,
                    sessions=float(tw.get("sessions", 0.0)),
                    users=float(tw.get("users", 0.0)),
                    conversion_rate=float(tw.get("conversion_rate", 0.0)),
                    add_to_cart_rate=float(tw.get("add_to_cart_rate", 0.0)),
                    purchases=float(tw.get("purchases", 0.0)),
                    page_views=float(tw.get("page_views", 0.0)),
                    bounce_rate=float(tw.get("bounce_rate", 0.0)),
                    cost_per_session=float(tw.get("cost_per_session", 0.0)),
                    cost_per_atc=float(tw.get("cost_per_atc", 0.0)),
                    revenue=float(tw.get("revenue", 0.0)),
                    ad_spend=float(tw.get("ad_spend", 0.0)),
                )
            )
            seeded["tw_summary_daily"] += 1

    existing_shopify = db.execute(select(SourceConfig).where(SourceConfig.source_name == "shopify")).scalar_one_or_none()
    existing_decision_engine = db.execute(select(SourceConfig).where(SourceConfig.source_name == "decision-engine")).scalar_one_or_none()
    existing_triplewhale = db.execute(select(SourceConfig).where(SourceConfig.source_name == "triplewhale")).scalar_one_or_none()

    if existing_shopify is None or (existing_shopify.sync_mode or "") == "seeded-prototype":
        upsert_source_config(
            db,
            "shopify",
            configured=shopify_seen,
            sync_mode="seeded-prototype",
            config_json={"seeded_from": str(processed_dir / "orders_daily.json")},
        )
    if existing_decision_engine is None or (existing_decision_engine.sync_mode or "") == "seeded-prototype":
        upsert_source_config(
            db,
            "decision-engine",
            configured=kpi_seen,
            sync_mode="seeded-prototype",
            config_json={"seeded_from": str(processed_dir / "kpi_daily.json")},
        )
    if existing_triplewhale is None or (existing_triplewhale.sync_mode or "") == "seeded-prototype":
        upsert_source_config(
            db,
            "triplewhale",
            configured=tw_seen,
            sync_mode="seeded-prototype",
            config_json={"seeded_from": str(processed_dir / "tw_metrics.json")},
        )

    db.commit()
    return seeded
