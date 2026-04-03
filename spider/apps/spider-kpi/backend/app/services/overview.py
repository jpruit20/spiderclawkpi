from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Alert, DriverDiagnostic, KPIDaily, Recommendation
from app.services.source_health import get_source_health


def is_incomplete_kpi_day(row: KPIDaily | None) -> bool:
    if row is None:
        return False
    sessions = row.sessions or 0
    orders = row.orders or 0
    revenue = row.revenue or 0
    return sessions == 0 and (orders > 0 or revenue > 0)


def build_overview(db: Session) -> dict:
    kpis = db.execute(select(KPIDaily).order_by(KPIDaily.business_date)).scalars().all()
    alerts = db.execute(select(Alert).order_by(desc(Alert.created_at)).limit(10)).scalars().all()
    diagnostics = db.execute(select(DriverDiagnostic).order_by(desc(DriverDiagnostic.business_date)).limit(10)).scalars().all()
    recommendations = db.execute(select(Recommendation).order_by(desc(Recommendation.created_at)).limit(10)).scalars().all()

    latest = None
    for row in reversed(kpis):
        if not is_incomplete_kpi_day(row):
            latest = row
            break
    return {
        "latest_kpi": latest,
        "daily_series": kpis,
        "alerts": alerts,
        "diagnostics": diagnostics,
        "recommendations": recommendations,
        "source_health": get_source_health(db),
    }
