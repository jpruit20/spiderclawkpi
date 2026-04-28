from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


settings = get_settings()

# SQLAlchemy connection pool sizing.
#
# The default 5 + 10 overflow = 15 connections is fine for an isolated
# CLI but far too small for a FastAPI dashboard backend that:
#   * serves multiple parallel API calls per page load (5-12 per page),
#   * runs scheduled jobs in-process (insights, materializers, telemetry
#     ingest, recommendations refresh, etc.), and
#   * accepts continuous /api/admin/ingest/telemetry-stream POSTs from
#     the field fleet.
#
# When the dashboard renders multiple pages or two users hit it during a
# batch ingest, the 15-connection ceiling exhausts and any new request
# hangs for `pool_timeout` (30s) before raising QueuePool TimeoutError
# → cascading 500s across every endpoint that needs the DB.
#
# Postgres `max_connections=100` on the droplet gives us ~85 of headroom
# above the worker's pool. Sizing 25 + 35 overflow = 60 max keeps a
# comfortable margin and matches realistic peak fan-out.
#
# pool_recycle=1800 protects against stale-connection drops if pg or any
# intermediate layer sweeps idle connections after ~30 min.
# pool_pre_ping keeps the existing health check on checkout.
_POOL_KW = dict(
    pool_size=25,
    max_overflow=35,
    pool_timeout=30,
    # Recycle every 5 min — short enough that a leaked / "idle in
    # transaction" handle gets reclaimed before the pool starves, long
    # enough that we don't churn fresh connections on healthy traffic.
    pool_recycle=300,
    pool_pre_ping=True,
)

# Postgres-side defenses for connection leaks. We've been seeing
# connections accumulate in "idle in transaction" state — the pool
# treats them as in-use, so the pool fills up even though the
# application has nominally moved on. These two settings tell PG to
# kill the session itself if a transaction has been idle that long,
# which forces the SQLAlchemy connection to be re-established on the
# next checkout (pool_pre_ping handles the dead-handle case).
#
#  - idle_in_transaction_session_timeout = 30s — abort any session
#    sitting in a transaction longer than 30s.
#  - statement_timeout = 60s — kill any single statement that runs
#    longer than 60s. Anything legitimately that slow needs to be
#    rewritten or moved to a background materializer, not held inline.
_CONNECT_ARGS = {
    "options": "-c idle_in_transaction_session_timeout=30000 -c statement_timeout=60000",
}

engine = create_engine(
    settings.database_url,
    future=True,
    connect_args=_CONNECT_ARGS,
    **_POOL_KW,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)


def reset_engine(database_url: str) -> None:
    global engine, SessionLocal
    engine.dispose()
    engine = create_engine(
        database_url, future=True, connect_args=_CONNECT_ARGS, **_POOL_KW,
    )
    SessionLocal.configure(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
