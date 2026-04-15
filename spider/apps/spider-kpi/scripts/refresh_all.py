#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = BASE_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.compute.kpis import recompute_daily_kpis, recompute_diagnostics  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.ingestion.connectors.freshdesk import sync_freshdesk  # noqa: E402
from app.ingestion.connectors.ga4 import sync_ga4  # noqa: E402
from app.ingestion.connectors.shopify import sync_shopify_orders  # noqa: E402
from app.ingestion.connectors.triplewhale import sync_triplewhale  # noqa: E402
from app.services.issue_radar import build_issue_radar  # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        freshdesk_result = sync_freshdesk(db, days=7)
        results = {
            "shopify": sync_shopify_orders(db),
            "triplewhale": sync_triplewhale(db, backfill_days=1),
            "ga4": sync_ga4(db, days=7),
            "freshdesk": freshdesk_result,
        }

        if any(result.get("ok") and not result.get("skipped") for result in results.values()):
            results["decision_engine"] = {
                "ok": True,
                "processed": recompute_daily_kpis(db),
            }
            recompute_diagnostics(db)
        else:
            results["decision_engine"] = {
                "ok": False,
                "skipped": True,
                "message": "No successful source syncs; compute skipped.",
            }

        # Rebuild issue radar cache after Freshdesk sync so /api/issues can
        # serve from the cluster/signal tables instead of re-classifying.
        if freshdesk_result.get("ok") and not freshdesk_result.get("skipped"):
            try:
                radar = build_issue_radar(db)
                results["issue_radar"] = {
                    "ok": True,
                    "clusters": len(radar.get("clusters", [])),
                    "signals": len(radar.get("signals", [])),
                }
            except Exception as exc:
                results["issue_radar"] = {"ok": False, "error": str(exc)}
        else:
            results["issue_radar"] = {
                "ok": False,
                "skipped": True,
                "message": "Freshdesk sync skipped; radar not rebuilt.",
            }

        print(json.dumps(results, default=str))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
