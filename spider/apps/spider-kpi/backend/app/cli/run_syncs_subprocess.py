"""Per-target run_syncs runner. Invoked once per connector by the
scheduler so each connector's per-call C-side memory leak is reclaimed
by the OS when this process exits.

Why per-target instead of one process for the whole sweep:
``app.cli.run_syncs_diagnose`` measured several connectors holding
hundreds of MB after gc + malloc_trim (aws_telemetry ~815 MB,
recompute_daily_kpis ~543 MB, materialize_app_side 2-3 GB peak). Even
the b445d22 single-subprocess wrapper OOM-killed because all of those
compounded inside one process — sum > 4 GB cgroup ceiling on the
droplet, three SIGKILLs in 13 minutes after the materialize-skip
stopgap landed. Running one connector per process means a leak in any
single one is bounded by that connector's own peak; the next target
starts with a fresh address space.

Usage:
    python -m app.cli.run_syncs_subprocess --target NAME

Targets are listed in ``TARGETS`` below. Each runs the connector plus
its tightly-coupled post-hooks (e.g. aws_telemetry triggers
cook_rederivation while results are fresh).

Gating (``_already_running`` checks, due-checks for the cron-style
optional connectors) happens INSIDE this subprocess so the parent's
dispatch loop can stay dumb. If the connector decides not to run,
the subprocess exits 0 quickly.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


# ── Per-target runners ───────────────────────────────────────────────


def _gate_already_running(db, source_name: str) -> bool:
    """Mirror of scheduler._already_running, lifted here so this
    subprocess can self-gate without importing scheduler.py (which
    would re-import the whole connector graph)."""
    from sqlalchemy import desc, select
    from app.models import SourceSyncRun
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
        return False
    return True


def _gate_due(db, source_name: str, interval_minutes: int) -> bool:
    """True if the named source is due for a refresh."""
    from sqlalchemy import desc, select
    from app.models import SourceSyncRun
    latest = db.execute(
        select(SourceSyncRun)
        .where(SourceSyncRun.source_name == source_name)
        .order_by(desc(SourceSyncRun.started_at))
        .limit(1)
    ).scalar_one_or_none()
    if latest is None or latest.started_at is None:
        return True
    return latest.started_at <= datetime.now(timezone.utc) - timedelta(minutes=interval_minutes)


def _run_shopify(db) -> None:
    if _gate_already_running(db, "shopify"):
        return
    from app.ingestion.connectors.shopify import sync_shopify_orders
    sync_shopify_orders(db)


def _run_triplewhale(db) -> None:
    if _gate_already_running(db, "triplewhale"):
        return
    from app.ingestion.connectors.triplewhale import sync_triplewhale
    sync_triplewhale(db, backfill_days=1)


def _run_freshdesk(db) -> None:
    """Freshdesk + materialize_app_side hook (latter still SKIPPED by
    stopgap — was the 2-3 GB peak)."""
    if _gate_already_running(db, "freshdesk"):
        return
    from app.ingestion.connectors.freshdesk import sync_freshdesk
    result = sync_freshdesk(db, days=7)
    ok = bool(result and result.get("ok") and not result.get("skipped"))
    if ok:
        logging.getLogger(__name__).warning(
            "app_side materialize SKIPPED (stopgap) — known 2-3 GB peak"
        )


def _run_ga4(db) -> None:
    if _gate_already_running(db, "ga4"):
        return
    from app.ingestion.connectors.ga4 import sync_ga4
    sync_ga4(db, days=7)


def _run_shipstation(db) -> None:
    """ShipStation v1 ingest, Spider-only stores. Cheap on delta runs;
    backfill mode (empty table) walks 4y history in 30-day windows
    and can take ~10-20 min depending on shipment volume.
    Self-gates via shipstation_sync_interval_minutes."""
    from app.core.config import get_settings
    settings = get_settings()
    if not (settings.shipstation_api_key and settings.shipstation_api_secret):
        return  # not configured
    if not _gate_due(db, "shipstation", settings.shipstation_sync_interval_minutes):
        return
    if _gate_already_running(db, "shipstation"):
        return
    from app.services.source_health import finish_sync_run, start_sync_run, upsert_source_config
    upsert_source_config(db, "shipstation", configured=True, enabled=True, sync_mode="poll")
    run = start_sync_run(db, "shipstation", "scheduled")
    try:
        from app.ingestion.connectors.shipstation import sync_shipstation
        result = sync_shipstation(db)
        records = result.get("shipments", {}).get("upserted", 0) if isinstance(result.get("shipments"), dict) else 0
        finish_sync_run(db, run, status="success", records_processed=records)
    except Exception as exc:
        finish_sync_run(db, run, status="failed", error_message=str(exc)[:500])
        raise


def _run_sharepoint(db) -> None:
    """SharePoint multi-tenant ingest. Cheap (~30-100 MB) — small
    document libraries on the AMW side. Self-gates due-checks via
    sharepoint_sync_interval_minutes (60 min default)."""
    from app.core.config import get_settings
    if not _gate_due(db, "sharepoint", get_settings().sharepoint_sync_interval_minutes):
        return
    if _gate_already_running(db, "sharepoint"):
        return
    from app.ingestion.connectors.sharepoint import sync_sharepoint
    sync_sharepoint(db)


def _run_sharepoint_deep_analysis(db) -> None:
    """Deep analysis pass: download + parse content for any active
    analyzable doc that doesn't have a fresh content row, run Claude
    per-file analysis on extracted content, then synthesize per-product
    narratives. Cheap on subsequent runs because both content and
    analysis layers cache on (source_modified_at, sha, version).

    Cost: ~$1-2 per full corpus pass (Haiku per-file + Opus synthesis).
    Gated via sharepoint_deep_analysis_sync_interval_minutes (default
    every 12 hours)."""
    from app.core.config import get_settings
    settings = get_settings()
    interval = getattr(settings, "sharepoint_deep_analysis_sync_interval_minutes", None) or 720
    if not _gate_due(db, "sharepoint_deep_analysis", interval):
        return
    if _gate_already_running(db, "sharepoint_deep_analysis"):
        return

    from app.services.source_health import finish_sync_run, start_sync_run, upsert_source_config
    upsert_source_config(db, "sharepoint_deep_analysis", configured=True, enabled=True, sync_mode="poll")
    run = start_sync_run(db, "sharepoint_deep_analysis", "scheduled")
    try:
        from app.services.sharepoint_content_extractor import extract_content_for_corpus
        from app.services.sharepoint_ai_analyzer import analyze_corpus
        from app.services.sharepoint_synthesizer import synthesize_all_products

        ec = extract_content_for_corpus(db)
        ac = analyze_corpus(db)
        sc = synthesize_all_products(db)

        records = (ac.get("ok", 0) or 0) + sum(1 for v in sc.values() if v.get("status") == "ok")
        finish_sync_run(db, run, status="success", records_processed=records)
    except Exception as exc:
        finish_sync_run(db, run, status="failed", error_message=str(exc)[:500])
        raise


def _run_sharepoint_intelligence(db) -> None:
    """Post-ingest semantic-layer pass: classify any newly-ingested
    docs (path/filename heuristics, fast), then download + parse any
    BOM/CBOM/price-list spreadsheets that haven't been extracted yet,
    then refresh the canonical-source picks for every (data_type,
    product, division) scope.

    Cheap unless many new BOMs landed — extraction is rate-limited by
    Graph API, ~1-3s per Excel file. The classifier is the bulk-UPDATE
    path so a 1000-row delta finishes in <2s. Gate due via
    sharepoint_intelligence_sync_interval_minutes (default = same as
    sharepoint sync so they run in lockstep)."""
    from app.core.config import get_settings
    settings = get_settings()
    interval = getattr(settings, "sharepoint_intelligence_sync_interval_minutes", None) or settings.sharepoint_sync_interval_minutes
    if not _gate_due(db, "sharepoint_intelligence", interval):
        return
    if _gate_already_running(db, "sharepoint_intelligence"):
        return

    from app.services.source_health import finish_sync_run, start_sync_run, upsert_source_config
    upsert_source_config(db, "sharepoint_intelligence", configured=True, enabled=True, sync_mode="poll")
    run = start_sync_run(db, "sharepoint_intelligence", "scheduled")
    try:
        from app.services.sharepoint_classify import classify_documents
        from app.services.sharepoint_bom_extractor import extract_all_bom_documents
        from app.services.sharepoint_canonical import resolve_canonical

        # 1. Classify any new/unclassified docs (idempotent, bulk UPDATE)
        classify_counts = classify_documents(db)

        # 2. Extract BOM lines for any active BOM/CBOM/price_list that
        #    doesn't have a successful extraction run yet
        extract_counts = extract_all_bom_documents(db)

        # 3. Refresh canonical picks. Cheap (small fanout).
        PRODUCTS = ["Huntsman", "Giant Huntsman", "Venom", "Webcraft", "Giant Webcraft"]
        DIVISIONS = ["pe", "manufacturing", "operations", None]
        DATA_TYPES = ["cogs", "bom", "vendor_list", "design_spec", "drawing"]
        canonical_picks = 0
        for dt in DATA_TYPES:
            for prod in PRODUCTS:
                for div in DIVISIONS:
                    if resolve_canonical(db, data_type=dt, spider_product=prod, dashboard_division=div, auto_persist=True):
                        canonical_picks += 1

        records = (classify_counts.get("updated", 0) or 0) + (extract_counts.get("lines", 0) or 0)
        finish_sync_run(
            db,
            run,
            status="success",
            records_processed=records,
        )
    except Exception as exc:
        finish_sync_run(db, run, status="failed", error_message=str(exc)[:500])
        raise


def _run_klaviyo(db) -> None:
    """Klaviyo profiles + events sync. Cheap-to-medium (~50-200 MB
    transient depending on backfill window). Lives in its own
    subprocess for the same memory-isolation reason as the others.
    Self-gates due-checks via klaviyo_sync_interval_minutes (60 min
    by default). 2026-04-26: was missing from this dispatch dict
    entirely after the per-target refactor — the scheduler's targets
    list was running it via the missing-target error path. Added."""
    from app.core.config import get_settings
    if not _gate_due(db, "klaviyo", get_settings().klaviyo_sync_interval_minutes):
        return
    if _gate_already_running(db, "klaviyo"):
        return
    from app.ingestion.connectors.klaviyo import sync_klaviyo
    sync_klaviyo(db)


def _run_aws_telemetry(db) -> None:
    """AWS telemetry + cook_rederivation. Heaviest connector
    (~815 MB held). Gets its own subprocess so its leak dies on exit."""
    if _gate_already_running(db, "aws_telemetry"):
        return
    from app.ingestion.connectors.aws_telemetry import sync_aws_telemetry
    result = sync_aws_telemetry(db)
    ok = bool(result and result.get("ok") and not result.get("skipped"))
    if ok:
        try:
            from app.services.cook_rederivation import run_cook_rederivation
            run_cook_rederivation(db)
        except Exception:
            logging.getLogger(__name__).exception("cook_rederivation after aws sync failed")
            db.rollback()


def _run_clarity(db) -> None:
    from app.core.config import get_settings
    if not _gate_due(db, "clarity", get_settings().clarity_sync_interval_minutes):
        return
    if _gate_already_running(db, "clarity"):
        return
    from app.ingestion.connectors.clarity import sync_clarity
    sync_clarity(db, days=1)


def _run_reddit(db) -> None:
    from app.core.config import get_settings
    if not _gate_due(db, "reddit", get_settings().reddit_sync_interval_minutes):
        return
    if _gate_already_running(db, "reddit"):
        return
    from app.ingestion.connectors.reddit import sync_reddit
    sync_reddit(db)


def _run_amazon(db) -> None:
    from app.core.config import get_settings
    if not _gate_due(db, "amazon", get_settings().amazon_sync_interval_minutes):
        return
    if _gate_already_running(db, "amazon"):
        return
    from app.ingestion.connectors.amazon import sync_amazon
    sync_amazon(db)


def _run_clickup(db) -> None:
    from app.core.config import get_settings
    if not _gate_due(db, "clickup", get_settings().clickup_sync_interval_minutes):
        return
    if _gate_already_running(db, "clickup"):
        return
    from app.ingestion.connectors.clickup import sync_clickup
    sync_clickup(db)


def _run_slack(db) -> None:
    from app.core.config import get_settings
    if not _gate_due(db, "slack", get_settings().slack_discovery_interval_minutes):
        return
    if _gate_already_running(db, "slack"):
        return
    from app.ingestion.connectors.slack import sync_slack
    sync_slack(db)


def _run_youtube(db) -> None:
    if not _gate_due(db, "youtube", 360):
        return
    if _gate_already_running(db, "youtube"):
        return
    from app.ingestion.connectors.youtube import sync_youtube
    sync_youtube(db)


def _run_youtube_lore(db) -> None:
    if not _gate_due(db, "youtube_lore", 24 * 60):
        return
    if _gate_already_running(db, "youtube_lore"):
        return
    from app.ingestion.connectors.youtube_lore import sync_youtube_lore
    sync_youtube_lore(db)


def _run_recompute_kpis(db) -> None:
    """Recompute the daily KPI rollup. Measured 2026-04-25 at ~543 MB
    held per call after gc + malloc_trim. On its own it's fine; it
    OOM'd previously only because it was running in the same subprocess
    as recompute_diagnostics (which adds another big working set)."""
    if _gate_already_running(db, "decision-engine"):
        return
    from app.compute.kpis import recompute_daily_kpis
    recompute_daily_kpis(db)


def _run_recompute_diagnostics(db) -> None:
    """Recompute the diagnostics rollup. Split out from recompute_kpis
    so the two don't compound memory in one subprocess."""
    if _gate_already_running(db, "decision-engine"):
        return
    from app.compute.kpis import recompute_diagnostics
    recompute_diagnostics(db)


TARGETS = {
    "shopify": _run_shopify,
    "triplewhale": _run_triplewhale,
    "freshdesk": _run_freshdesk,
    "ga4": _run_ga4,
    "klaviyo": _run_klaviyo,
    "shipstation": _run_shipstation,
    "sharepoint": _run_sharepoint,
    "sharepoint_intelligence": _run_sharepoint_intelligence,
    "sharepoint_deep_analysis": _run_sharepoint_deep_analysis,
    "aws_telemetry": _run_aws_telemetry,
    "clarity": _run_clarity,
    "reddit": _run_reddit,
    "amazon": _run_amazon,
    "clickup": _run_clickup,
    "slack": _run_slack,
    "youtube": _run_youtube,
    "youtube_lore": _run_youtube_lore,
    "recompute_kpis": _run_recompute_kpis,
    "recompute_diagnostics": _run_recompute_diagnostics,
}


def main() -> int:
    _configure_logging()
    log = logging.getLogger("run_syncs_subprocess")

    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=False, default=None,
                        help="single target to run; if omitted, runs the legacy combined sweep (deprecated)")
    args = parser.parse_args()

    if args.target is None:
        # Legacy path: the combined sweep. Kept for backward compat
        # but the parent should now invoke this script per-target so
        # each connector's leak dies independently.
        log.warning("run_syncs subprocess (legacy combined sweep) starting")
        try:
            from app.scheduler import _run_syncs_inner
            _run_syncs_inner()
        except Exception:
            log.exception("run_syncs subprocess (legacy) crashed")
            return 1
        log.warning("run_syncs subprocess (legacy) complete")
        return 0

    if args.target not in TARGETS:
        log.error("unknown target: %s (valid: %s)", args.target, sorted(TARGETS))
        return 2

    log.warning("run_syncs subprocess starting target=%s", args.target)
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        TARGETS[args.target](db)
        try:
            db.commit()
        except Exception:
            db.rollback()
    except Exception:
        log.exception("target=%s crashed", args.target)
        try:
            db.rollback()
        except Exception:
            pass
        return 1
    finally:
        try:
            db.close()
        except Exception:
            pass
    log.warning("run_syncs subprocess complete target=%s", args.target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
