from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_dashboard_session
from app.compute.kpis import get_data_quality
from app.models import Alert, CommunityMessage, CXAction, DriverDiagnostic, FreshdeskAgentDaily, FreshdeskTicket, FreshdeskTicketConversation, IssueCluster, IssueSignal, KPIDaily, KPIIntraday, Recommendation, ReviewMention, ShopifyAnalyticsDaily, ShopifyOrderDaily, SocialMention, TWSummaryDaily
from app.schemas.overview import AlertOut, CXActionOut, CXActionUpdateIn, CXSnapshotOut, DataQualityOut, DiagnosticOut, KPIDailyOut, OverviewResponse, RecommendationOut, SourceHealthOut, TelemetrySummaryOut
from app.services.cx_actions import evaluateActionClosure, evaluateCustomerExperienceActions
from app.services.cx_snapshot import build_customer_experience_snapshot
from app.services.issue_radar import build_issue_radar, get_cluster_ticket_detail, read_cached_issue_radar
from app.services.telemetry import summarize_telemetry
from app.services.telemetry_history_daily import get_cook_analysis_for_range, get_telemetry_history_daily
from app.services.clarity_analytics import get_product_page_health, get_ux_friction_report
from app.services.overview import OVERVIEW_LOOKBACK_DAYS, build_kpi_payload, build_overview
from app.services.social_listening import get_amazon_product_health, get_brand_pulse, get_market_intelligence, get_social_mentions, get_social_trends, get_youtube_performance
from app.services.source_health import get_source_health

router = APIRouter(prefix="/api", tags=["overview"], dependencies=[Depends(require_dashboard_session)])
BUSINESS_TZ = ZoneInfo("America/New_York")


@router.get("/overview", response_model=OverviewResponse)
def get_overview(db: Session = Depends(db_session)) -> OverviewResponse:
    return OverviewResponse.model_validate(build_overview(db))


@router.get("/kpis/daily", response_model=list[KPIDailyOut])
def get_kpis_daily(db: Session = Depends(db_session)):
    cutoff = datetime.now(BUSINESS_TZ).date() - timedelta(days=OVERVIEW_LOOKBACK_DAYS)
    rows = db.execute(
        select(KPIDaily).where(KPIDaily.business_date >= cutoff).order_by(KPIDaily.business_date)
    ).scalars().all()
    shopify_map = {row.business_date: row for row in db.execute(select(ShopifyOrderDaily).where(ShopifyOrderDaily.business_date >= cutoff)).scalars().all()}
    shopify_analytics_map = {row.business_date: row for row in db.execute(select(ShopifyAnalyticsDaily).where(ShopifyAnalyticsDaily.business_date >= cutoff)).scalars().all()}
    tw_map = {row.business_date: row for row in db.execute(select(TWSummaryDaily).where(TWSummaryDaily.business_date >= cutoff)).scalars().all()}
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
    # Read from the pre-computed cache. The radar is rebuilt by the
    # Freshdesk sync in refresh_all.py; building on every GET used to
    # cost 20-60s on a warm DB. Bootstrap path still builds once.
    cached = read_cached_issue_radar(db)
    if cached is not None:
        return cached
    return build_issue_radar(db)


@router.post("/issues/rebuild")
def rebuild_issues(db: Session = Depends(db_session)):
    # Manual trigger for admins to force a radar rebuild (e.g. after
    # correcting classifier keywords). Normally the nightly refresh
    # pipeline rebuilds automatically after a Freshdesk sync.
    return build_issue_radar(db)


@router.get("/issues/clusters/{theme}/detail")
def get_cluster_detail(theme: str, db: Session = Depends(db_session)):
    return get_cluster_ticket_detail(db, theme)


@router.get("/support/overview")
def get_support_overview(db: Session = Depends(db_session)):
    cutoff = datetime.now(BUSINESS_TZ).date() - timedelta(days=OVERVIEW_LOOKBACK_DAYS)
    kpis = db.execute(
        select(KPIDaily).where(KPIDaily.business_date >= cutoff).order_by(KPIDaily.business_date)
    ).scalars().all()
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
def telemetry_summary(
    days: int = 30,
    start: str | None = None,
    end: str | None = None,
    db: Session = Depends(db_session),
):
    # When start/end are given, the dashboard date picker is authoritative
    # and every block in the payload is scoped to that window. Without them
    # we fall back to the trailing `days` window (clamped to 365 to protect
    # telemetry_stream_events).
    start_date = date.fromisoformat(start) if start else None
    end_date = date.fromisoformat(end) if end else None
    days = max(1, min(days, 365))
    payload = summarize_telemetry(db, lookback_days=days, start=start_date, end=end_date)
    payload['history_daily'] = get_telemetry_history_daily(
        db,
        limit=days,
        start=start_date,
        end=end_date,
    )
    return payload


@router.get("/telemetry/cook-analysis")
def telemetry_cook_analysis(
    start: str = "2024-01-01",
    end: str | None = None,
    db: Session = Depends(db_session),
):
    if end is None:
        from datetime import datetime, timezone
        end = datetime.now(timezone.utc).date().isoformat()
    return get_cook_analysis_for_range(db, start, end)


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


@router.get("/social/youtube-performance")
def get_youtube_performance_endpoint(days: int = 30, db: Session = Depends(db_session)):
    return get_youtube_performance(db, days)


@router.get("/social/amazon-products")
def get_amazon_products_endpoint(db: Session = Depends(db_session)):
    return get_amazon_product_health(db)


@router.get("/social/market-intelligence")
def get_market_intelligence_endpoint(days: int = 30, db: Session = Depends(db_session)):
    return get_market_intelligence(db, days)


@router.get("/clarity/friction")
def get_clarity_friction(db: Session = Depends(db_session)):
    return get_ux_friction_report(db)


@router.get("/clarity/page-health")
def get_clarity_page_health(db: Session = Depends(db_session)):
    return get_product_page_health(db)


@router.get("/data-quality", response_model=DataQualityOut)
def data_quality(db: Session = Depends(db_session)):
    return get_data_quality(db)


@router.get("/engineering/issues")
def get_engineering_issues():
    from app.services.github_issues import get_p0_p1_issues
    return get_p0_p1_issues()


def _split_terms(raw: str) -> list[str]:
    return [t.strip() for t in raw.split(",") if t.strip()]


@router.get("/complaints/by-product")
def complaints_by_product(
    q: str,
    aliases: str = "",
    days: int = 180,
    sample: int = 8,
    db: Session = Depends(db_session),
):
    """Count tickets + social posts that mention a product across the archive.

    `q` is the canonical product term; `aliases` is comma-separated alt spellings.
    Returns per-source counts with a small sample of the matching records so
    the UI can render evidence alongside the number.
    """
    terms = [q.strip()] + _split_terms(aliases)
    terms = [t for t in terms if t]
    if not terms:
        raise HTTPException(status_code=400, detail="q is required")
    days = max(1, min(days, 1825))
    sample = max(1, min(sample, 25))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    patterns = [f"%{t}%" for t in terms]

    def _ilike_any(column):
        return or_(*[column.ilike(p) for p in patterns])

    subject_matches = _ilike_any(FreshdeskTicket.subject)
    desc_text_matches = _ilike_any(FreshdeskTicket.description_text)
    ticket_filter = or_(subject_matches, desc_text_matches)
    ticket_q = (
        select(FreshdeskTicket)
        .where(FreshdeskTicket.created_at_source >= since)
        .where(ticket_filter)
        .order_by(desc(FreshdeskTicket.created_at_source))
    )
    ticket_rows = db.execute(ticket_q).scalars().all()

    conv_ticket_ids_q = (
        select(FreshdeskTicketConversation.ticket_id)
        .where(FreshdeskTicketConversation.created_at_source >= since)
        .where(_ilike_any(FreshdeskTicketConversation.body_text))
        .distinct()
    )
    conv_ticket_ids = {row[0] for row in db.execute(conv_ticket_ids_q).all()}

    ticket_ids_in_primary = {t.ticket_id for t in ticket_rows}
    extra_ids = conv_ticket_ids - ticket_ids_in_primary
    if extra_ids:
        extra_rows = db.execute(
            select(FreshdeskTicket)
            .where(FreshdeskTicket.ticket_id.in_(extra_ids))
            .order_by(desc(FreshdeskTicket.created_at_source))
        ).scalars().all()
        ticket_rows = list(ticket_rows) + list(extra_rows)
        ticket_rows.sort(key=lambda t: t.created_at_source or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    total_tickets = len(ticket_rows)
    ticket_sample = [
        {
            "ticket_id": t.ticket_id,
            "subject": t.subject,
            "status": t.status,
            "priority": t.priority,
            "created_at": t.created_at_source.isoformat() if t.created_at_source else None,
            "csat_score": t.csat_score,
            "matched_in_conversation": t.ticket_id in (conv_ticket_ids - ticket_ids_in_primary),
        }
        for t in ticket_rows[:sample]
    ]

    social_rows = db.execute(
        select(SocialMention)
        .where(SocialMention.published_at >= since)
        .where(
            or_(
                _ilike_any(SocialMention.title),
                _ilike_any(SocialMention.body),
                _ilike_any(SocialMention.product_mentioned),
            )
        )
        .order_by(desc(SocialMention.published_at))
    ).scalars().all()
    total_social = len(social_rows)
    social_sample = [
        {
            "platform": s.platform,
            "title": s.title,
            "body": (s.body or "")[:400],
            "sentiment": s.sentiment,
            "source_url": s.source_url,
            "published_at": s.published_at.isoformat() if s.published_at else None,
        }
        for s in social_rows[:sample]
    ]

    review_rows = db.execute(
        select(ReviewMention)
        .where(ReviewMention.published_at >= since)
        .where(or_(_ilike_any(ReviewMention.body), _ilike_any(ReviewMention.product)))
        .order_by(desc(ReviewMention.published_at))
    ).scalars().all()
    review_sample = [
        {
            "source": r.source,
            "rating": r.rating,
            "body": (r.body or "")[:400],
            "sentiment": r.sentiment,
            "url": r.url,
            "published_at": r.published_at.isoformat() if r.published_at else None,
        }
        for r in review_rows[:sample]
    ]

    community_rows = db.execute(
        select(CommunityMessage)
        .where(CommunityMessage.published_at >= since)
        .where(or_(_ilike_any(CommunityMessage.body), _ilike_any(CommunityMessage.product)))
        .order_by(desc(CommunityMessage.published_at))
    ).scalars().all()
    community_sample = [
        {
            "source": c.source,
            "channel": c.channel,
            "body": (c.body or "")[:400],
            "sentiment": c.sentiment,
            "published_at": c.published_at.isoformat() if c.published_at else None,
        }
        for c in community_rows[:sample]
    ]

    return {
        "query": q,
        "aliases": terms[1:],
        "days": days,
        "counts": {
            "freshdesk_tickets": total_tickets,
            "freshdesk_conversations_with_match": len(conv_ticket_ids),
            "social_mentions": total_social,
            "review_mentions": len(review_rows),
            "community_messages": len(community_rows),
            "total": total_tickets + total_social + len(review_rows) + len(community_rows),
        },
        "samples": {
            "tickets": ticket_sample,
            "social": social_sample,
            "reviews": review_sample,
            "community": community_sample,
        },
    }
