from app.compute.kpis import recompute_daily_kpis, recompute_diagnostics
from app.db.session import SessionLocal
from app.ingestion.connectors.freshdesk import sync_freshdesk
from app.ingestion.connectors.shopify import sync_shopify_orders
from app.ingestion.connectors.triplewhale import sync_triplewhale


def main() -> int:
    db = SessionLocal()
    try:
        print(sync_shopify_orders(db))
        print(sync_triplewhale(db, backfill_days=1))
        print(sync_freshdesk(db, days=7))
        print({"kpis_processed": recompute_daily_kpis(db)})
        recompute_diagnostics(db)
        print({"ok": True})
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
