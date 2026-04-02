from pathlib import Path

from app.compute.kpis import recompute_daily_kpis, recompute_diagnostics
from app.db.session import SessionLocal
from app.services.seed import seed_from_prototype_files


def main() -> int:
    base_dir = Path("/home/jpruit20/.openclaw/workspace/spider-kpi")
    db = SessionLocal()
    try:
        seeded = seed_from_prototype_files(db, base_dir)
        recompute_daily_kpis(db)
        recompute_diagnostics(db)
        print(seeded)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
