from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_dashboard_session
from app.compute.kpis import get_data_quality
from app.models import Alert, CXAction, DriverDiagnostic, FreshdeskAgentDaily, FreshdeskTicket, IssueCluster, IssueSignal, KPIDaily, KPIIntraday, Recommendation, ShopifyAnalyticsDaily, ShopifyOrderDaily, TWSummaryDaily
from app.schemas.overview import AlertOut, CXActionOut, CXActionUpdateIn, CXSnapshotOut, DataQualityOut, DiagnosticOut, KPIDailyOut, OverviewResponse, RecommendationOut, SourceHealthOut, TelemetrySummaryOut
from app.services.cx_actions import evaluateActionClosure, evaluateCustomerExperienceActions
from app.services.cx_snapshot import build_customer_experience_snapshot
from app.services.issue_radar import build_issue_radar
from app.services.telemetry import summarize_telemetry
from app.services.telemetry_history_daily import get_telemetry_history_daily
from app.services.clarity_analytics import get_product_page_health, get_ux_friction_report
from app.services.overview import build_kpi_payload, build_overview
from app.services.social_listening import get_brand_pulse, get_social_mentions, get_social_trends
from app.services.source_health import get_source_health

router = APIRouter(prefix="/api", tags=["overview"], dependencies=[Depends(require_dashboard_session)])
BUSINESS_TZ = ZoneInfo("America/New_York")


@router.get("/overview", response_model=OverviewResponse)
def get_overview(db: Session = Depends(db_session)) -> OverviewResponse:
    return OverviewResponse.model_validate(build_overview(db))


@router.get("/kpis/daily", response_model=list[KPIDailyOut])
def get_kpis_daily(db: Session = Depends(db_session)):
    rows = db.execute(select(KPIDaily).order_by(KPIDaily.business_date)).scalars().all()
    shopify_map = {row.business_date: row for row in db.execute(select(ShopifyOrderDaily)).scalars().all()}
    shopify_analytics_map = {row.business_date: row for row in db.execute(select(ShopifyAnalyticsDaily)).scalars().all()}
    tw_map = {row.business_date: row for row in db.execute(select(TWSummaryDaily)).scalars().all()}
    return [build_kpi_payload(row, shopify_map, shopify_analytics_map, tw_map) for row in rows] if rows else []


@router.get("/kpis/intraday")
def get_kpis_intraday(db: Session = Depends(db_session)):
    rows = db.execute(select(KPIIntraday).order_by(desc(KPIIntraday.bucket_start)).limit(1)).scalars().all()
    return {"latest": rows[0] if rows else None}


@router.get("/kpis/intraday-series")
def get_kpis_intraday_series(db: Session = Depends(db_session)):
    rows = db.execute(select(KPIIntraday).order_by(KPIIntraday.bucket_start)).scalars().all()
    payload = [
        {
            "bucket_start": row.bucket_start,
            "business_date": row.bucket_start.astimezone(BUSINESS_TZ).date().isoformat() if row.bucket_start else None,
            "hour_label": row.bucket_start.astimezone(BUSINESS_TZ).strftime("%H:%M") if row.bucket_start else None,
            "revenue": row.revenue,
            "sessions": row.sessions,
            "orders": row.orders,
        }
        for row in rows
    ]
    return {"rows": payload}


@router.get("/diagnostics", response_model=list[DiagnosticOut])
def get_diagnostics(db: Session = Depends(db_session)):
    return db.execute(select(DriverDiagnostic).order_by(desc(DriverDiagnostic.business_date))).scalars().all()


@router.get("/alerts", response_model=list[AlertOut])
def get_alerts(db: Session = Depends(db_session)):
    return db.execute(select(Alert).order_by(desc(Alert.created_at))).scalars().all()


@router.get("/recommendations", response_model=list[RecommendationOut])
def get_recommendations(db: Session = Depends(db_session)):
    return db.execute(select(Recommendation).order_by(desc(Recommendation.created_at))).scalars().all()


@router.get("/issues")
def get_issues(db: Session = Depends(db_session)):
    return build_issue_radar(db)


@router.get("/support/overview")
def get_support_overview(db: Session = Depends(db_session)):
    kpis = db.execute(select(KPIDaily).order_by(KPIDaily.business_date)).scalars().all()
    return {"rows": kpis}


@router.get("/support/agents")
def get_support_agents(db: Session = Depends(db_session)):
    rows = db.execute(select(FreshdeskAgentDaily).order_by(FreshdeskAgentDaily.business_date, FreshdeskAgentDaily.agent_name, FreshdeskAgentDaily.agent_id)).scalars().all()
    return rows


@router.get("/support/tickets")
def get_support_tickets(db: Session = Depends(db_session)):
    tickets = db.execute(select(FreshdeskTicket).order_by(desc(FreshdeskTicket.updated_at_source))).scalars().all()
    return tickets


@router.get("/source-health", response_model=list[SourceHealthOut])
def get_sources(db: Session = Depends(db_session)):
    return get_source_health(db)


@router.get("/telemetry/summary", response_model=TelemetrySummaryOut)
def telemetry_summary(db: Session = Depends(db_session)):
    payload = summarize_telemetry(db)
    payload['history_daily'] = get_telemetry_history_daily(db)
    return payload


@router.get("/telemetry/history-daily")
def telemetry_history_daily(db: Session = Depends(db_session)):
    return get_telemetry_history_daily(db)


@router.get("/cx/snapshot", response_model=CXSnapshotOut)
def get_cx_snapshot(db: Session = Depends(db_session)):
    evaluateCustomerExperienceActions(db)
    evaluateActionClosure(db)
    db.commit()
    return build_customer_experience_snapshot(db)


@router.get("/cx/actions", response_model=list[CXActionOut])
def get_cx_actions(status: str | None = None, db: Session = Depends(db_session)):
    evaluateCustomerExperienceActions(db)
    evaluateActionClosure(db)
    db.commit()
    query = select(CXAction).order_by(desc(CXAction.updated_at))
    if status:
        query = query.where(CXAction.status == status)
    return db.execute(query).scalars().all()


@router.post("/cx/actions/{action_id}/update", response_model=CXActionOut)
def update_cx_action(action_id: str, payload: CXActionUpdateIn, db: Session = Depends(db_session)):
    action = db.execute(select(CXAction).where(CXAction.id == action_id)).scalar_one_or_none()
    if action is None:
        raise HTTPException(status_code=404, detail='Action not found')
    if payload.status not in {'open', 'in_progress', 'resolved'}:
        raise HTTPException(status_code=400, detail='Invalid status')
    action.status = payload.status
    action.updated_at = datetime.now(timezone.utc)
    action.resolved_at = datetime.now(timezone.utc) if payload.status == 'resolved' else None
    db.commit()
    db.refresh(action)
    return action


@router.get("/social/mentions")
def get_social_mentions_endpoint(platform: str | None = None, classification: str | None = None, days: int = 7, db: Session = Depends(db_session)):
    return get_social_mentions(db, platform, classification, days)


@router.get("/social/pulse")
def get_social_pulse(days: int = 7, db: Session = Depends(db_session)):
    return get_brand_pulse(db, days)


@router.get("/social/trends")
def get_social_trends_endpoint(days: int = 30, db: Session = Depends(db_session)):
    return get_social_trends(db, days)


@router.get("/clarity/friction")
def get_clarity_friction(db: Session = Depends(db_session)):
    return get_ux_friction_report(db)


@router.get("/clarity/page-health")
def get_clarity_page_health(db: Session = Depends(db_session)):
    return get_product_page_health(db)


@router.get("/data-quality", response_model=DataQualityOut)
def data_quality(db: Session = Depends(db_session)):
    return get_data_quality(db)
