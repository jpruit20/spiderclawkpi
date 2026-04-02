from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Alert, DriverDiagnostic, KPIDaily, Recommendation
from app.services.source_health import get_source_health


def build_overview(db: Session) -> dict:
    kpis = db.execute(select(KPIDaily).order_by(KPIDaily.business_date)).scalars().all()
    alerts = db.execute(select(Alert).order_by(desc(Alert.created_at)).limit(10)).scalars().all()
    diagnostics = db.execute(select(DriverDiagnostic).order_by(desc(DriverDiagnostic.business_date)).limit(10)).scalars().all()
    recommendations = db.execute(select(Recommendation).order_by(desc(Recommendation.created_at)).limit(10)).scalars().all()

    latest = kpis[-1] if kpis else None
    return {
        "latest_kpi": latest,
        "daily_series": kpis,
        "alerts": alerts,
        "diagnostics": diagnostics,
        "recommendations": recommendations,
        "source_health": get_source_health(db),
    }
