"""Tier 2 materialized-cache runtime.

Expensive endpoints register a builder under a short cache_key. A
scheduler job runs every N minutes and calls each builder, writing the
result to the ``aggregate_cache`` table. API endpoints read by key,
get back a payload in <20 ms regardless of how expensive the underlying
compute was.

Shape contract:
    register(key, builder_fn)         — wire up; builder_fn(db) -> JSON-safe dict
    get(db, key)                      — read cached row, or None
    rebuild(db, key)                  — force one builder to run now
    rebuild_all(db)                   — run every registered builder
    build_if_missing(db, key)         — lazy fill on first request before the
                                        scheduler has run

Callers that want cache-first behavior pattern:

    entry = aggregate_cache.get(db, 'cx:snapshot:v1')
    if entry is None:
        entry = aggregate_cache.build_if_missing(db, 'cx:snapshot:v1')
    return entry.payload  # + entry.computed_at for freshness badges
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AggregateCache


logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    key: str
    payload: dict
    computed_at: datetime
    duration_ms: int
    source_version: str

    def age_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.computed_at).total_seconds()


BuilderFn = Callable[[Session], dict]

_BUILDERS: dict[str, BuilderFn] = {}
_VERSIONS: dict[str, str] = {}


def register(cache_key: str, builder: BuilderFn, source_version: str = "v1") -> None:
    """Wire a cache key to the function that computes its payload."""
    _BUILDERS[cache_key] = builder
    _VERSIONS[cache_key] = source_version


def registered_keys() -> list[str]:
    return sorted(_BUILDERS.keys())


def _jsonify(value: Any) -> Any:
    """Coerce a payload to JSON-safe types. Pydantic models → dict,
    datetimes → isoformat strings, Decimals → floats."""
    try:
        return json.loads(json.dumps(value, default=str))
    except (TypeError, ValueError) as e:
        raise ValueError(f"Cache payload is not JSON-serializable: {e}")


def get(db: Session, cache_key: str) -> Optional[CacheEntry]:
    row = db.execute(
        select(AggregateCache).where(AggregateCache.cache_key == cache_key)
    ).scalars().first()
    if row is None:
        return None
    # Bust stale entries if the builder's source_version moved forward.
    current_version = _VERSIONS.get(cache_key)
    if current_version and row.source_version != current_version:
        return None
    return CacheEntry(
        key=row.cache_key,
        payload=row.payload_json or {},
        computed_at=row.computed_at,
        duration_ms=row.duration_ms or 0,
        source_version=row.source_version,
    )


def put(
    db: Session,
    cache_key: str,
    payload: dict,
    duration_ms: int,
    source_version: Optional[str] = None,
) -> CacheEntry:
    payload_json = _jsonify(payload)
    version = source_version or _VERSIONS.get(cache_key, "v1")
    now = datetime.now(timezone.utc)
    row = db.execute(
        select(AggregateCache).where(AggregateCache.cache_key == cache_key)
    ).scalars().first()
    if row is None:
        row = AggregateCache(cache_key=cache_key)
        db.add(row)
    row.payload_json = payload_json
    row.computed_at = now
    row.duration_ms = duration_ms
    row.source_version = version
    db.commit()
    return CacheEntry(
        key=cache_key, payload=payload_json,
        computed_at=now, duration_ms=duration_ms, source_version=version,
    )


def rebuild(db: Session, cache_key: str) -> CacheEntry:
    """Run the registered builder for ``cache_key`` and persist the result."""
    builder = _BUILDERS.get(cache_key)
    if builder is None:
        raise ValueError(f"No builder registered for cache key {cache_key!r}")
    started = time.time()
    try:
        payload = builder(db)
    except Exception:
        logger.exception("cache builder failed for %s", cache_key)
        db.rollback()
        raise
    duration_ms = int((time.time() - started) * 1000)
    entry = put(db, cache_key, payload, duration_ms)
    logger.info("aggregate_cache rebuilt %s in %dms", cache_key, duration_ms)
    return entry


def rebuild_all(db: Session) -> dict[str, Any]:
    """Run every registered builder. Used by the scheduler."""
    results: dict[str, Any] = {}
    for key in registered_keys():
        try:
            entry = rebuild(db, key)
            results[key] = {"ok": True, "duration_ms": entry.duration_ms}
        except Exception as e:
            results[key] = {"ok": False, "error": str(e)[:200]}
    return results


def build_if_missing(db: Session, cache_key: str) -> Optional[CacheEntry]:
    """Serve-first fallback: if the scheduler hasn't populated the key
    yet (e.g. fresh deploy), compute it synchronously on the request
    path. Returns None if no builder is registered."""
    entry = get(db, cache_key)
    if entry is not None:
        return entry
    if cache_key not in _BUILDERS:
        return None
    return rebuild(db, cache_key)
