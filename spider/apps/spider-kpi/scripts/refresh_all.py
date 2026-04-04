#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


BASE_DIR = Path("/home/jpruit20/.openclaw/workspace/spider/apps/spider-kpi")
BACKEND_DIR = BASE_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.compute.kpis import recompute_daily_kpis, recompute_diagnostics  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.ingestion.connectors.freshdesk import sync_freshdesk  # noqa: E402
from app.ingestion.connectors.shopify import sync_shopify_orders  # noqa: E402
from app.ingestion.connectors.triplewhale import sync_triplewhale  # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        results = {
            "shopify": sync_shopify_orders(db),
            "triplewhale": sync_triplewhale(db, backfill_days=1),
            "freshdesk": sync_freshdesk(db, days=7),
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

        print(json.dumps(results, default=str))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
