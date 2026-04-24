from pathlib import Path
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from app.compute.app_side import materialize_app_side
from app.compute.kpis import recompute_daily_kpis, recompute_diagnostics
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.ingestion.connectors.aws_telemetry import sync_aws_telemetry
from app.services.beta_verdict import run_beta_verdict_pass
from app.services.cook_behavior_baselines import rebuild_cook_behavior_baselines
from app.services.cook_behavior_backtest import run_cook_behavior_backtest
from app.services.cook_rederivation import run_cook_rederivation
from app.services.freshdesk_cook_correlation import run_freshdesk_cook_correlation
from app.ingestion.connectors.clarity import sync_clarity
from app.ingestion.connectors.clickup import sync_clickup
from app.ingestion.connectors.freshdesk import sync_freshdesk
from app.ingestion.connectors.ga4 import sync_ga4
from app.ingestion.connectors.shopify import sync_shopify_orders
from app.ingestion.connectors.slack import sync_slack
from app.ingestion.connectors.triplewhale import sync_triplewhale
from app.models import SourceConfig, SourceSyncRun
from app.services.seed import seed_from_prototype_files
from sqlalchemy import desc, select


settings = get_settings()
BASE_DIR = Path(__file__).resolve().parents[2]


def _already_running(db, source_name: str) -> bool:
    """Check if a connector is already running. Auto-expires stale runs (>30 min)."""
    run = db.execute(
        select(SourceSyncRun)
        .where(SourceSyncRun.source_name == source_name, SourceSyncRun.status == "running")
        .order_by(desc(SourceSyncRun.started_at))
        .limit(1)
    ).scalars().first()
    if run is None:
        return False
    started_at = run.started_at or run.created_at
    if started_at and started_at < datetime.now(timezone.utc) - timedelta(minutes=30):
        run.status = "failed"
        run.finished_at = datetime.now(timezone.utc)
        run.error_message = "Stale running sync auto-expired by scheduler (>30 min)."
        run.metadata_json = {**(run.metadata_json or {}), "auto_expired": True, "expired_at": datetime.now(timezone.utc).isoformat()}
        db.add(run)
        db.commit()
        return False  # allow new run to start
    return True


def _successful_result(result: dict | None) -> bool:
    if not result:
        return False
    return bool(result.get("ok")) and not bool(result.get("skipped"))


def run_seed() -> None:
    db = SessionLocal()
    try:
        existing_live_configs = db.execute(
            select(SourceConfig).where(
                SourceConfig.source_name.in_(["shopify", "triplewhale", "ga4", "clarity", "freshdesk", "aws_telemetry"])
            )
        ).scalars().all()
        if any(
            cfg and cfg.configured and (cfg.sync_mode or "") != "seeded-prototype"
            for cfg in existing_live_configs
        ):
            return
        seeded = seed_from_prototype_files(db, BASE_DIR)
        if any(seeded.values()) and not _already_running(db, "decision-engine"):
            recompute_daily_kpis(db)
            recompute_diagnostics(db)
    finally:
        db.close()


def run_syncs() -> None:
    db = SessionLocal()
    try:
        any_success = False
        if not _already_running(db, "shopify"):
            any_success = _successful_result(sync_shopify_orders(db)) or any_success
        if not _already_running(db, "triplewhale"):
            any_success = _successful_result(sync_triplewhale(db, backfill_days=1)) or any_success
        freshdesk_success = False
        if not _already_running(db, "freshdesk"):
            freshdesk_success = _successful_result(sync_freshdesk(db, days=7))
            any_success = freshdesk_success or any_success
        if freshdesk_success:
            try:
                materialize_app_side(db)
            except Exception:
                # Materializer failure should not abort the scheduler sweep.
                import logging
                logging.getLogger(__name__).exception("app_side materialize failed")
                db.rollback()
        if not _already_running(db, "ga4"):
            any_success = _successful_result(sync_ga4(db, days=7)) or any_success
        aws_success = False
        if not _already_running(db, "aws_telemetry"):
            aws_success = _successful_result(sync_aws_telemetry(db))
            any_success = aws_success or any_success
        # After AWS/S3 telemetry lands, re-score any newly inserted
        # telemetry_sessions rows so the PID-quality / intent / outcome
        # model stays live. Idempotent: only touches cook_intent IS NULL.
        if aws_success:
            try:
                run_cook_rederivation(db)
            except Exception:
                import logging
                logging.getLogger(__name__).exception("cook_rederivation after aws sync failed")
                db.rollback()
        latest_clarity_run = db.execute(
            select(SourceSyncRun)
            .where(SourceSyncRun.source_name == "clarity")
            .order_by(desc(SourceSyncRun.started_at))
            .limit(1)
        ).scalar_one_or_none()
        clarity_due = (
            latest_clarity_run is None
            or latest_clarity_run.started_at is None
            or latest_clarity_run.started_at <= datetime.now(timezone.utc) - timedelta(minutes=settings.clarity_sync_interval_minutes)
        )
        if clarity_due and not _already_running(db, "clarity"):
            any_success = _successful_result(sync_clarity(db, days=1)) or any_success
        latest_reddit_run = db.execute(
            select(SourceSyncRun)
            .where(SourceSyncRun.source_name == "reddit")
            .order_by(desc(SourceSyncRun.started_at))
            .limit(1)
        ).scalar_one_or_none()
        reddit_due = (
            latest_reddit_run is None
            or latest_reddit_run.started_at is None
            or latest_reddit_run.started_at <= datetime.now(timezone.utc) - timedelta(minutes=settings.reddit_sync_interval_minutes)
        )
        if reddit_due and not _already_running(db, "reddit"):
            from app.ingestion.connectors.reddit import sync_reddit
            any_success = _successful_result(sync_reddit(db)) or any_success
        latest_amazon_run = db.execute(
            select(SourceSyncRun)
            .where(SourceSyncRun.source_name == "amazon")
            .order_by(desc(SourceSyncRun.started_at))
            .limit(1)
        ).scalar_one_or_none()
        amazon_due = (
            latest_amazon_run is None
            or latest_amazon_run.started_at is None
            or latest_amazon_run.started_at <= datetime.now(timezone.utc) - timedelta(minutes=settings.amazon_sync_interval_minutes)
        )
        if amazon_due and not _already_running(db, "amazon"):
            from app.ingestion.connectors.amazon import sync_amazon
            any_success = _successful_result(sync_amazon(db)) or any_success
        latest_clickup_run = db.execute(
            select(SourceSyncRun)
            .where(SourceSyncRun.source_name == "clickup")
            .order_by(desc(SourceSyncRun.started_at))
            .limit(1)
        ).scalar_one_or_none()
        clickup_due = (
            latest_clickup_run is None
            or latest_clickup_run.started_at is None
            or latest_clickup_run.started_at <= datetime.now(timezone.utc) - timedelta(minutes=settings.clickup_sync_interval_minutes)
        )
        if clickup_due and not _already_running(db, "clickup"):
            any_success = _successful_result(sync_clickup(db)) or any_success
        latest_slack_run = db.execute(
            select(SourceSyncRun)
            .where(SourceSyncRun.source_name == "slack")
            .order_by(desc(SourceSyncRun.started_at))
            .limit(1)
        ).scalar_one_or_none()
        slack_due = (
            latest_slack_run is None
            or latest_slack_run.started_at is None
            or latest_slack_run.started_at <= datetime.now(timezone.utc) - timedelta(minutes=settings.slack_discovery_interval_minutes)
        )
        if slack_due and not _already_running(db, "slack"):
            any_success = _successful_result(sync_slack(db)) or any_success
        latest_youtube_run = db.execute(
            select(SourceSyncRun)
            .where(SourceSyncRun.source_name == "youtube")
            .order_by(desc(SourceSyncRun.started_at))
            .limit(1)
        ).scalar_one_or_none()
        youtube_due = (
            latest_youtube_run is None
            or latest_youtube_run.started_at is None
            or latest_youtube_run.started_at <= datetime.now(timezone.utc) - timedelta(minutes=360)
        )
        if youtube_due and not _already_running(db, "youtube"):
            from app.ingestion.connectors.youtube import sync_youtube
            any_success = _successful_result(sync_youtube(db)) or any_success
        # YouTube -> Lore runs once a day (quota-heavy: walks full
        # uploads playlist). Piggybacks on the same 6h gate as the
        # social-mention sync but checks its own SourceSyncRun row.
        latest_youtube_lore_run = db.execute(
            select(SourceSyncRun)
            .where(SourceSyncRun.source_name == "youtube_lore")
            .order_by(desc(SourceSyncRun.started_at))
            .limit(1)
        ).scalar_one_or_none()
        youtube_lore_due = (
            latest_youtube_lore_run is None
            or latest_youtube_lore_run.started_at is None
            or latest_youtube_lore_run.started_at <= datetime.now(timezone.utc) - timedelta(hours=24)
        )
        if youtube_lore_due and not _already_running(db, "youtube_lore"):
            from app.ingestion.connectors.youtube_lore import sync_youtube_lore
            any_success = _successful_result(sync_youtube_lore(db)) or any_success
        if any_success and not _already_running(db, "decision-engine"):
            recompute_daily_kpis(db)
            recompute_diagnostics(db)
    finally:
        db.close()


def run_beta_verdict_job() -> None:
    """Daily post-deploy verdict sweep for every non-draft firmware
    release. Closes the loop: did the update actually fix the issues it
    targeted on opted-in devices?"""
    db = SessionLocal()
    try:
        run_beta_verdict_pass(db)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("beta verdict pass failed")
        db.rollback()
    finally:
        db.close()


def run_cook_behavior_rebuild_job() -> None:
    """Nightly: rebuild cook_behavior_baselines + run backtest + refresh
    freshdesk↔cook correlations. Runs at 08:30 UTC / 04:30 ET, before the
    beta-verdict job, so classifier predictions use today's latest stats."""
    db = SessionLocal()
    try:
        # Backtest FIRST — scores the *current* (about-to-be-replaced)
        # baselines against the latest sessions, so we can tell if the
        # new rebuild actually improves predictive accuracy.
        try:
            run_cook_behavior_backtest(db)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("cook_behavior backtest failed")
            db.rollback()
        try:
            rebuild_cook_behavior_baselines(db)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("cook_behavior rebuild failed")
            db.rollback()
        try:
            run_freshdesk_cook_correlation(db, lookback_days=14)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("freshdesk_cook_correlation failed")
            db.rollback()
    finally:
        db.close()


def run_aggregate_cache_rebuild_job() -> None:
    """Every 15 min: rebuild every registered aggregate-cache builder.

    Endpoints served from this cache see <20 ms read paths (just a
    single SELECT by cache_key, no heavy aggregation). This job is the
    only place the expensive compute runs. Any builder that fails is
    logged; the rest continue.
    """
    db = SessionLocal()
    try:
        import app.services.cache_builders  # noqa: F401 — registers builders
        from app.services.aggregate_cache import rebuild_all
        results = rebuild_all(db)
        import logging as _logging
        _logging.getLogger(__name__).info("aggregate_cache rebuild_all: %s", results)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("aggregate_cache rebuild_all failed")
        db.rollback()
    finally:
        db.close()


def run_taxonomy_cache_warmer_job() -> None:
    """Keep the product-taxonomy builders hot.

    ``build_huntsman_device_ids``, ``build_t2_max_by_device``, and
    ``build_test_cohort_device_ids`` each scan millions of rows on a
    cold cache (measured 2026-04-24: 21 s, 16 s, 25 s respectively —
    ~63 s combined), and every fleet/firmware/charcoal endpoint
    depends on them. Without a warmer the 5-min TTL guarantees that
    one unlucky request every five minutes eats the full cold path
    and trips nginx's 60 s timeout (observed as
    ``/api/fleet/size: Request timed out`` on the Product Engineering
    page).

    These return sets of device_ids (small; no leak risk like the
    cohort burn pool), so we can safely refresh at a sub-TTL cadence.
    Runs at boot +10 s and every 4 min.
    """
    db = SessionLocal()
    try:
        from app.services.product_taxonomy import (
            build_huntsman_device_ids,
            build_t2_max_by_device,
            build_test_cohort_device_ids,
        )
        import time as _time
        import logging as _log
        log = _log.getLogger(__name__)
        for label, fn in (
            ("huntsman_device_ids", build_huntsman_device_ids),
            ("t2_max_by_device", build_t2_max_by_device),
            ("test_cohort_device_ids", build_test_cohort_device_ids),
        ):
            t0 = _time.monotonic()
            try:
                out = fn(db, force=True)
                log.info("taxonomy warmer: %s refreshed in %.1fs (n=%s)", label, _time.monotonic() - t0, len(out))
            except Exception:
                log.exception("taxonomy warmer: %s refresh failed", label)
                db.rollback()
    finally:
        db.close()


def run_stream_session_builder_job() -> None:
    """Hourly: build TelemetrySession rows from live stream events.

    Replaces the dead DynamoDB scan path. Picks up from the last
    stream-built session and walks forward, writing sessions with
    source_event_id prefix 'stream:'. S3 backfill rows are preserved.
    """
    db = SessionLocal()
    try:
        from app.services.stream_session_builder import run_scheduler_tick
        r = run_scheduler_tick(db)
        import logging as _log
        _log.getLogger(__name__).info("stream_session_builder tick: %s", r)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("stream_session_builder failed")
        db.rollback()
    finally:
        db.close()


def run_weekly_gauge_selection_job() -> None:
    """Monday 10:00 UTC / 06:00 ET: Opus picks the 8 Command Center
    priority gauges for the coming week. Idempotent per (iso_week_start,
    rank); respects pinned gauges from the prior week."""
    db = SessionLocal()
    try:
        from app.services.weekly_gauges_selector import run_weekly_gauge_selection
        run_weekly_gauge_selection(db)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("weekly_gauge_selection failed")
        db.rollback()
    finally:
        db.close()


def run_partner_catalog_refresh_job() -> None:
    """Daily 10:30 UTC / 06:30 ET: refresh every registered partner's
    product catalog (retail prices, stock status, new SKUs). Runs
    before the JIT forecast job so the financial math uses today's
    prices, not yesterday's."""
    db = SessionLocal()
    try:
        from app.services.partner_catalog import refresh_all_partners
        result = refresh_all_partners(db)
        import logging as _log
        _log.getLogger(__name__).info("partner catalog refresh: %s", result)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("partner catalog refresh failed")
        db.rollback()
    finally:
        db.close()


def run_charcoal_jit_forecast_job() -> None:
    """Daily 11:00 UTC / 07:00 ET: re-forecast every non-cancelled
    Charcoal JIT subscription. Also auto-fills shipping_zip from
    Shopify orders when the subscription has a user_key (email) but
    no zip yet, and re-keys synthetic mac:xxx device_ids once real
    telemetry arrives.

    Dry-run only. Writes last_forecast_json + next_ship_after on each
    row. No Shopify draft orders created — that trigger stays manual
    until the predictions are trusted.
    """
    db = SessionLocal()
    try:
        from app.services.charcoal_jit import run_daily_forecast_pass
        result = run_daily_forecast_pass(db)
        import logging as _log
        _log.getLogger(__name__).info("charcoal_jit forecast pass: %s", result)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("charcoal_jit forecast pass failed")
        db.rollback()
    finally:
        db.close()


def run_charcoal_jit_invitations_expire_job() -> None:
    """Daily: flip any past-expiry pending invitations to ``expired`` so
    the status column stays truthful. Idempotent — cheap after the
    first pass each day."""
    db = SessionLocal()
    try:
        from app.services.charcoal_jit_invitations import expire_stale_invitations
        result = expire_stale_invitations(db)
        import logging as _log
        _log.getLogger(__name__).info("charcoal_jit invitation expiry: %s", result)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("charcoal_jit invitation expiry failed")
        db.rollback()
    finally:
        db.close()


def run_cohort_burn_pool_warmer_job() -> None:
    """Every 4 min: pre-build the per-device burn pool used by the
    charcoal modeling endpoint for both lookback windows (90d + 180d).

    The pool is the heavy part of compute_cohort_model — decoding every
    JSONB actual_temp_time_series in the window, 17K+ sessions, ~500MB
    transient memory. With this job running we keep the process-local
    TTL cache warm, so the modeling slider UI always hits in-memory
    math (~ms) instead of the cold DB+decode path (60+ s, which nginx
    502s at).

    Safe to run in parallel with user traffic because the cache is
    populated under a lock and reads return the old value until the
    new one is in place.
    """
    from datetime import datetime, timezone
    db = SessionLocal()
    try:
        from app.services.charcoal_jit import _build_device_burn_pool
        now = datetime.now(timezone.utc)
        for lb in (90, 180):
            try:
                # force=True rebuilds unconditionally; TTL is 5 min and
                # we run every 4 min, so the cache never goes cold
                # between warmer ticks.
                _build_device_burn_pool(db, lookback_days=lb, now=now, force=True)
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "cohort burn pool warmup failed for lookback=%s", lb
                )
                db.rollback()
    finally:
        db.close()


def run_ai_self_grade_job() -> None:
    """Weekly Sunday 14:00 UTC / 10:00 ET: Opus grades the last 7d of
    AI-generated artifacts against the team's feedback reactions and
    proposes a prompt_delta for the insight engine. The delta is NOT
    auto-applied — Joseph approves each one explicitly via the UI."""
    db = SessionLocal()
    try:
        from app.services.ai_self_grade import run_weekly_self_grade
        run_weekly_self_grade(db)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("ai_self_grade failed")
        db.rollback()
    finally:
        db.close()


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(run_seed, "date", id="seed-on-start", max_instances=1, coalesce=True)
    scheduler.add_job(run_syncs, "interval", minutes=settings.sync_interval_minutes, id="sync-all", replace_existing=True, max_instances=1, coalesce=True)
    # Daily post-deploy verdict sweep: compares shadow-signal firings
    # before vs after each opted-in device's t0 across addresses_issues
    # tags. 09:00 UTC / 05:00 ET — after the main sync cycle has had a
    # chance to land any new telemetry overnight.
    scheduler.add_job(run_beta_verdict_job, "cron", hour=9, minute=0, id="beta-verdict-daily", replace_existing=True, max_instances=1, coalesce=True)
    # Nightly cook-behavior knowledge-base rebuild + self-evaluation.
    # Runs before beta-verdict so downstream jobs see fresh baselines.
    scheduler.add_job(run_cook_behavior_rebuild_job, "cron", hour=8, minute=30, id="cook-behavior-nightly", replace_existing=True, max_instances=1, coalesce=True)
    # Weekly Sunday 14:00 UTC / 10:00 ET — Opus grades its own last-7d
    # output against team feedback. Proposes a prompt_delta that Joseph
    # approves (or rejects) from the dashboard.
    scheduler.add_job(run_ai_self_grade_job, "cron", day_of_week="sun", hour=14, minute=0, id="ai-self-grade-weekly", replace_existing=True, max_instances=1, coalesce=True)
    # Weekly Monday 10:00 UTC / 06:00 ET — Opus picks the Command Center
    # priority gauges for the coming week. Replaces the static 4-tile
    # top strip with a curated 8-gauge cluster whose selection adapts to
    # what's actually important this week (active DECI decisions,
    # recent incidents, 28-day KPI momentum).
    scheduler.add_job(run_weekly_gauge_selection_job, "cron", day_of_week="mon", hour=10, minute=0, id="weekly-gauge-selection", replace_existing=True, max_instances=1, coalesce=True)
    # Stream-based session builder. Fills the gap left by the dead
    # DynamoDB scan path. Fires 30 s after boot (so fresh processes get
    # at least one tick even if they get OOM-killed before the first
    # interval elapses) then every 10 min — the short interval is a
    # hedge against the process instability that kept stalling the old
    # 60-min cadence between 2026-04-18 and 2026-04-24. The builder is
    # idempotent (ON CONFLICT on source_event_id) so running it this
    # often costs a cheap DISTINCT-device scan most of the time.
    scheduler.add_job(
        run_stream_session_builder_job,
        "date",
        run_date=datetime.now(timezone.utc) + timedelta(seconds=30),
        id="stream-session-builder-boot",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(run_stream_session_builder_job, "interval", minutes=10, id="stream-session-builder", replace_existing=True, max_instances=1, coalesce=True)
    # Taxonomy cache warmer — keeps the expensive huntsman_ids /
    # t2_max_by_device / test_cohort_ids builders hot so
    # fleet/firmware/charcoal endpoints never pay the full 60 s
    # cold-cache path. Small memory footprint (sets of device_ids),
    # so sub-TTL cadence is safe.
    scheduler.add_job(
        run_taxonomy_cache_warmer_job,
        "date",
        run_date=datetime.now(timezone.utc) + timedelta(seconds=10),
        id="taxonomy-cache-warmup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(run_taxonomy_cache_warmer_job, "interval", minutes=4, id="taxonomy-cache-refresh", replace_existing=True, max_instances=1, coalesce=True)
    # Tier 2 cache: rebuild every 15 min. The first run happens
    # ~15 min after boot; endpoints fall back to synchronous
    # build_if_missing before then so the first request on a fresh
    # deploy is slower but correct.
    scheduler.add_job(run_aggregate_cache_rebuild_job, "interval", minutes=15, id="aggregate-cache-rebuild", replace_existing=True, max_instances=1, coalesce=True)
    # Daily charcoal JIT forecast pass at 11:00 UTC / 07:00 ET — after
    # the overnight sync cycle so trailing-burn windows include the
    # latest sessions. Dry-run only until Joseph flips shipment triggers.
    # Partner catalog refresh at 10:30 UTC / 06:30 ET — runs just
    # before the JIT forecast so financial math uses today's prices.
    scheduler.add_job(run_partner_catalog_refresh_job, "cron", hour=10, minute=30, id="partner-catalog-refresh-daily", replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(run_charcoal_jit_forecast_job, "cron", hour=11, minute=0, id="charcoal-jit-forecast-daily", replace_existing=True, max_instances=1, coalesce=True)
    # Expire stale beta-invitation rows daily at 11:05 UTC — runs right
    # after the forecast pass so the Beta rollout tab always renders
    # today's true status without manual refresh.
    scheduler.add_job(run_charcoal_jit_invitations_expire_job, "cron", hour=11, minute=5, id="charcoal-jit-invitations-expire-daily", replace_existing=True, max_instances=1, coalesce=True)
    # Cohort-modeling burn pool warmup. The once-per-boot warmup stays
    # (primes the cache so the first charcoal-modeling request after a
    # restart doesn't cold-start the JSONB decode and 502 at nginx).
    # The every-4-min refresh job was the primary driver of the OOM
    # killer loop observed 2026-04-18 → 2026-04-24: each run pinned
    # ~500 MB of transient memory without releasing it before the next
    # run allocated again, growing RSS from ~350 MB to ~3.7 GB every
    # 7-10 min until the kernel SIGKILL'd the process. We serve cold
    # reads (5-min TTL) until the leak is root-caused and fixed.
    scheduler.add_job(
        run_cohort_burn_pool_warmer_job,
        "date",
        run_date=datetime.now(timezone.utc) + timedelta(seconds=15),
        id="cohort-burn-pool-warmup",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    return scheduler
