"""Deploy-time guardrails: rate limits, batch cap, circuit breaker.

Sits between the deploy route and ``firmware_ota.create_job``. Every
guardrail reads from ``firmware_deploy_log`` — there is no in-memory
state that could be lost on a restart. The circuit breaker writes to
``.env`` on the droplet so the flip persists across restarts and
survives the process that tripped it.

Thresholds live in ``Settings`` (``core/config.py``). Joseph set the
initial values 2026-04-20:

  * 5 pushes/min for single-device deploys (per-initiator)
  * 50-device cap per batch
  * 60s between waves
  * Circuit breaker: 10% failure rate over last 10 completed deploys
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import FirmwareDeployLog


logger = logging.getLogger(__name__)


class GuardrailError(RuntimeError):
    """Raised when a deploy request violates a guardrail.

    The message is surfaced to the dashboard verbatim, so keep it terse
    and actionable ("wait 42s before retrying", not "INTERNAL ERROR").
    """


def check_batch_cap(device_count: int) -> None:
    settings = get_settings()
    if device_count > settings.firmware_ota_batch_cap:
        raise GuardrailError(
            f"Batch size {device_count} exceeds cap of {settings.firmware_ota_batch_cap}. "
            f"Split into waves."
        )


def check_rate_limit(db: Session, *, initiated_by: str) -> None:
    """Per-user sliding-window rate limit on deploy initiations.

    Counts rows inserted into ``firmware_deploy_log`` in the last 60s for
    this caller. Batch deploys only count as one "initiation" — the
    sliding window is about intent-to-deploy, not per-device fan-out.
    """
    settings = get_settings()
    since = datetime.now(timezone.utc) - timedelta(seconds=60)
    # Distinct (aws_job_id) so a 50-device batch counts once.
    recent = (
        db.query(func.count(func.distinct(FirmwareDeployLog.aws_job_id)))
        .filter(
            FirmwareDeployLog.initiated_by == initiated_by,
            FirmwareDeployLog.created_at >= since,
            FirmwareDeployLog.aws_job_id.isnot(None),
        )
        .scalar()
    ) or 0
    if recent >= settings.firmware_ota_single_rate_per_min:
        raise GuardrailError(
            f"Rate limit: {recent} deploys in the last 60s from {initiated_by}. "
            f"Max {settings.firmware_ota_single_rate_per_min}/min. Wait and retry."
        )


def evaluate_circuit_breaker(db: Session) -> Optional[str]:
    """Check the last N *completed* deploys for failure rate.

    Returns a string reason if the breaker should trip, else ``None``.
    Only considers rows with a terminal status. Devices still in
    ``pending`` or ``in_flight`` do not count toward either numerator or
    denominator — the breaker fires based on what we actually know.
    """
    settings = get_settings()
    terminal = ("succeeded", "failed", "rolled_back", "aborted")
    rows = (
        db.query(FirmwareDeployLog.status)
        .filter(FirmwareDeployLog.status.in_(terminal))
        .order_by(FirmwareDeployLog.finished_at.desc().nulls_last())
        .limit(settings.firmware_ota_circuit_breaker_window)
        .all()
    )
    if len(rows) < settings.firmware_ota_circuit_breaker_window:
        return None  # not enough history to decide

    failures = sum(1 for (s,) in rows if s in ("failed", "rolled_back"))
    rate_pct = 100.0 * failures / len(rows)
    if rate_pct >= settings.firmware_ota_circuit_breaker_threshold_pct:
        return (
            f"Circuit breaker tripped: {failures}/{len(rows)} recent deploys failed "
            f"({rate_pct:.1f}% >= {settings.firmware_ota_circuit_breaker_threshold_pct}% threshold). "
            f"OTA disabled automatically."
        )
    return None


def trip_kill_switch(reason: str) -> None:
    """Flip ``FIRMWARE_OTA_ENABLED`` to ``false`` and persist to ``.env``.

    We write into the same ``.env`` that pydantic loads on boot, so the
    flip survives a process restart. We don't mutate ``os.environ`` only,
    because the next cron/uvicorn restart would re-read the file and
    re-enable. The circuit breaker should be sticky until a human
    investigates.

    Safety: if the .env path is missing or unwritable, we still log loudly
    so the oncall sees it. The in-memory Settings cache is cleared so
    subsequent ``_require_enabled()`` calls block immediately.
    """
    settings = get_settings()
    env_path = _find_env_file()
    try:
        if env_path and env_path.exists():
            _rewrite_env_var(env_path, "FIRMWARE_OTA_ENABLED", "false")
    except Exception:
        logger.exception("failed to persist FIRMWARE_OTA_ENABLED=false to %s", env_path)

    # Flip in-memory too so the current request stops cascading.
    settings.firmware_ota_enabled = False  # type: ignore[misc]
    get_settings.cache_clear()  # lru_cache

    logger.error("FIRMWARE KILL SWITCH TRIPPED: %s", reason)


def _find_env_file() -> Optional[Path]:
    """Locate the .env Settings reads from. Mirrors core/config.ROOT_DIR."""
    # core/config.py resolves ROOT_DIR = parents[3] of that file. Replicate.
    backend_root = Path(__file__).resolve().parents[2]
    candidate = backend_root / ".env"
    return candidate if candidate.parent.exists() else None


def _rewrite_env_var(path: Path, key: str, value: str) -> None:
    """Rewrite ``KEY=value`` in an ``.env`` file in place, preserving
    surrounding lines. Appends if not present."""
    lines = path.read_text().splitlines()
    prefix = f"{key}="
    found = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(prefix) and not stripped.startswith("#"):
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n")
