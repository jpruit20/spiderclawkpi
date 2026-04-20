"""AWS IoT Jobs wrapper for firmware OTA.

All functions in this module are gated by ``settings.firmware_ota_enabled``.
When the kill switch is off, every call raises ``OtaDisabledError`` before
touching AWS — the dashboard can display deploy UI, but no request will ever
reach IoT Core.

Why this module exists as a single choke-point:

* There is exactly one place that calls ``boto3.client('iot')`` for firmware
  pushes. If we need to disable OTA in an emergency (bad release detected,
  mass rollback, credentials rotation), we flip one env var and every code
  path blocks. The circuit breaker (``firmware_guardrails.py``) writes to
  this same flag when failure thresholds trip.
* The functions return typed ``dict`` shapes the routes can log directly
  into ``firmware_deploy_log.aws_response_json``. Callers never see raw
  botocore responses; they see only the fields that matter for audit.
* No retry logic here. AWS IoT Jobs ``CreateJob`` is idempotent on
  ``jobId``, so the caller can safely retry the same ``jobId`` — that's the
  right place for retry policy, not this wrapper.

Firmware-side context (for reviewers):
The device subscribes to ``$aws/things/<thing>/jobs/notify-next``; when
AWS delivers a job there, the device publishes ``start-next`` and receives
the full job document. It validates ``version``, ``sha256``, ``size``,
``expected_model`` / ``model_override`` on its own — see
``nhd_ota_validate_job`` in ``SG_FIRMWARE_V2/components/nhd_aws_iot_ota_update``.
So we do not re-implement those checks here; we only need to produce a
well-formed job document and a valid target list.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from app.core.config import get_settings

try:  # boto3 is already a dep (used by app_backend + telemetry ingest)
    import boto3  # type: ignore
    from botocore.exceptions import BotoCoreError, ClientError  # type: ignore
except Exception:  # pragma: no cover
    boto3 = None  # type: ignore
    BotoCoreError = Exception  # type: ignore
    ClientError = Exception  # type: ignore


logger = logging.getLogger(__name__)


class OtaDisabledError(RuntimeError):
    """Raised whenever OTA is attempted while the kill switch is off."""


class OtaConfigError(RuntimeError):
    """Raised when credentials or endpoint configuration is missing."""


@dataclass(frozen=True)
class JobDocument:
    """The JSON body that ends up on the device, verbatim.

    Field names and types must match ``nhd_ota_validate_job`` exactly or
    the device will reject the job at the firmware-side validation gate
    (see ``nhd_aws_iot_ota_update.c``). Keep this dataclass aligned with
    that C code — it is the source of truth.
    """
    version: str
    url: str
    sha256: str
    size: int
    expected_model: str  # "huntsman" | "kettle"
    model_override: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "url": self.url,
            "sha256": self.sha256.lower(),
            "size": int(self.size),
            "expected_model": self.expected_model.lower(),
            "model_override": bool(self.model_override),
        }


def _require_enabled() -> None:
    settings = get_settings()
    if not settings.firmware_ota_enabled:
        raise OtaDisabledError(
            "FIRMWARE_OTA_ENABLED is false — refusing to touch AWS IoT. "
            "Flip the env var on the droplet only after you are certain "
            "nothing is actively rolling out."
        )


def _iot_client():
    _require_enabled()
    settings = get_settings()
    if boto3 is None:
        raise OtaConfigError("boto3 is not installed in this environment")
    if not settings.aws_access_key_id or not settings.aws_secret_access_key:
        raise OtaConfigError(
            "AWS credentials missing — set aws_access_key_id / aws_secret_access_key "
            "in the droplet .env"
        )
    return boto3.client(
        "iot",
        region_name=settings.firmware_ota_aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )


def _thing_arn(device_id: str) -> str:
    """Return the full ARN for a device_id (which IS the thing name).

    ``device_id`` stored in ``telemetry_stream_events`` is the 32-char MD5
    hex the firmware computes from MAC + suffix. AWS IoT uses that exact
    string as the thing name, so no re-derivation is needed.

    Account id is discovered at runtime via ``sts:GetCallerIdentity`` on
    first use so this file stays hardcoded-ARN-free.
    """
    account = _get_account_id()
    region = get_settings().firmware_ota_aws_region
    return f"arn:aws:iot:{region}:{account}:thing/{device_id}"


_cached_account_id: Optional[str] = None


def _get_account_id() -> str:
    global _cached_account_id
    if _cached_account_id:
        return _cached_account_id
    settings = get_settings()
    sts = boto3.client(
        "sts",
        region_name=settings.firmware_ota_aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )
    _cached_account_id = sts.get_caller_identity()["Account"]
    return _cached_account_id  # type: ignore[return-value]


def create_job(
    *,
    job_id: str,
    device_ids: list[str],
    document: JobDocument,
    description: str,
    wave_delay_seconds: Optional[int] = None,
) -> dict[str, Any]:
    """Create an AWS IoT Job that delivers ``document`` to ``device_ids``.

    ``jobId`` should be stable per (release, cohort, batch) so retries are
    idempotent. ``targetSelection=SNAPSHOT`` means the target list is
    frozen at job creation — devices added to a thing-group later will
    NOT receive this job, which is what we want for controlled rollouts.

    Returns a slim dict for audit logging. Raw boto response is discarded.
    """
    client = _iot_client()
    settings = get_settings()

    if not device_ids:
        raise ValueError("device_ids is empty")
    if len(device_ids) > settings.firmware_ota_batch_cap:
        raise ValueError(
            f"device_ids={len(device_ids)} exceeds batch cap "
            f"({settings.firmware_ota_batch_cap}) — split into waves"
        )

    targets = [_thing_arn(d) for d in device_ids]
    rollout = {
        "maximumPerMinute": min(
            max(1, settings.firmware_ota_single_rate_per_min * max(1, len(device_ids) // 5)),
            100,
        ),
    }
    if wave_delay_seconds is None:
        wave_delay_seconds = settings.firmware_ota_wave_delay_seconds
    timeout_cfg = {"inProgressTimeoutInMinutes": 60}

    import json as _json
    try:
        resp = client.create_job(
            jobId=job_id,
            targets=targets,
            document=_json.dumps(document.to_dict()),
            description=description[:2028],
            targetSelection="SNAPSHOT",
            jobExecutionsRolloutConfig=rollout,
            timeoutConfig=timeout_cfg,
        )
    except (BotoCoreError, ClientError) as exc:
        logger.exception("create_job failed", extra={"job_id": job_id})
        raise

    return {
        "job_id": resp.get("jobId"),
        "job_arn": resp.get("jobArn"),
        "targets": targets,
        "requested_at_ms": int(time.time() * 1000),
        "rollout": rollout,
        "timeout_config": timeout_cfg,
    }


def describe_job_execution(*, job_id: str, device_id: str) -> dict[str, Any]:
    """Fetch current execution status for one (job, device) pair.

    Used by the audit polling loop to transition a deploy_log row from
    ``pending`` → ``in_flight`` → ``succeeded`` / ``failed`` /
    ``rolled_back``. IoT Jobs guarantees the execution status moves
    through: QUEUED → IN_PROGRESS → {SUCCEEDED, FAILED, REJECTED,
    TIMED_OUT, REMOVED, CANCELED}.
    """
    client = _iot_client()
    try:
        resp = client.describe_job_execution(jobId=job_id, thingName=device_id)
    except ClientError as exc:
        # Missing execution = caller should treat as "job removed or never created"
        code = exc.response.get("Error", {}).get("Code", "")  # type: ignore[union-attr]
        if code in {"ResourceNotFoundException"}:
            return {"status": "NOT_FOUND", "device_id": device_id, "job_id": job_id}
        raise

    execution = resp.get("execution", {}) or {}
    return {
        "status": execution.get("status"),
        "status_details": execution.get("statusDetails", {}),
        "queued_at": execution.get("queuedAt"),
        "started_at": execution.get("startedAt"),
        "last_updated_at": execution.get("lastUpdatedAt"),
        "version_number": execution.get("versionNumber"),
        "execution_number": execution.get("executionNumber"),
        "device_id": device_id,
        "job_id": job_id,
    }


def cancel_job(*, job_id: str, reason: str) -> dict[str, Any]:
    """Cancel a job before devices start picking it up. Best-effort.

    AWS will move QUEUED executions to CANCELED; devices already running
    IN_PROGRESS cannot be interrupted remotely — the firmware download
    completes or fails on its own.
    """
    client = _iot_client()
    try:
        resp = client.cancel_job(jobId=job_id, reasonCode="dashboard_abort", comment=reason[:127])
    except (BotoCoreError, ClientError):
        logger.exception("cancel_job failed", extra={"job_id": job_id})
        raise
    return {
        "job_id": resp.get("jobId"),
        "job_arn": resp.get("jobArn"),
        "description": resp.get("description"),
    }
