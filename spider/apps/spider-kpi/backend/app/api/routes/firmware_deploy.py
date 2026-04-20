"""Firmware deploy endpoints — two-phase, owner-gated, kill-switched.

Flow:

1. ``POST /api/firmware/deploy/preview`` — runs preflight, returns a
   single-use token with 10-minute TTL plus the structured device
   verdict. The dashboard renders this verdict so the user can see
   *every* reason a device is blocked before they ever type the
   confirmation phrase.

2. ``POST /api/firmware/deploy/execute`` — takes the token, a typed
   confirmation string (must equal the target version), and optionally a
   list of device_ids to override-deploy despite soft blocks. Creates
   one AWS IoT Job, writes one ``firmware_deploy_log`` row per device,
   and returns the aws_job_id for the UI to poll.

3. ``POST /api/firmware/deploy/abort`` — cancel a job by id.

4. ``GET /api/firmware/deploy/log`` — paged audit log.

5. ``GET /api/firmware/deploy/status/{job_id}`` — polls AWS once, updates
   the deploy_log rows for this job, returns the latest state.

6. ``POST /api/firmware/releases/{id}/approve`` — flip ``approved_for_*``
   flags. Writes an append-only entry to ``approval_audit_json``.

Every endpoint is gated by the same ``_require_owner`` dependency as
ECRs — email must equal ``joseph@spidergrills.com``. This is an
intentional belt-and-suspenders duplication of the frontend
``OwnerOnlyRoute`` because the backend is the real trust boundary.

A request that passes auth but fails ``FIRMWARE_OTA_ENABLED`` still gets
a 503 with the canonical ``OtaDisabledError`` message; the UI shows
that directly so the user learns about the kill switch instead of
"something went wrong".
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.api.routes.auth import get_user_from_request
from app.core.config import get_settings
from app.models.entities import (
    FirmwareDeployLog,
    FirmwareDeployPreviewToken,
    FirmwareRelease,
)
from app.services import firmware_guardrails, firmware_ota, firmware_preflight


logger = logging.getLogger(__name__)

OWNER_EMAIL = "joseph@spidergrills.com"


def _require_owner(request: Request, db: Session = Depends(db_session)) -> str:
    user = get_user_from_request(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Dashboard session required")
    email = (user.email or "").lower()
    if email != OWNER_EMAIL:
        raise HTTPException(status_code=403, detail="Firmware deploy is owner-only")
    return email


router = APIRouter(
    prefix="/api/firmware/deploy",
    tags=["firmware-deploy"],
    dependencies=[Depends(_require_owner)],
)


# ---------------------------------------------------------------------------
# Pydantic bodies
# ---------------------------------------------------------------------------


class PreviewBody(BaseModel):
    release_id: int
    cohort: Literal["alpha", "beta", "gamma"]
    device_ids: list[str] = Field(default_factory=list)
    macs: list[str] = Field(default_factory=list)


class ExecuteBody(BaseModel):
    preview_token: str
    confirm_version_typed: str = Field(
        description=(
            "User must type the target firmware version exactly. "
            "Belt-and-suspenders guard against fat-finger deploys."
        )
    )
    override_device_ids: list[str] = Field(
        default_factory=list,
        description="device_ids the caller is explicitly overriding soft blocks on (Alpha/Beta only)",
    )
    override_reason: Optional[str] = None


class AbortBody(BaseModel):
    aws_job_id: str
    reason: str


class ApproveBody(BaseModel):
    cohort: Literal["alpha", "beta", "gamma"]
    approve: bool = True
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


@router.post("/preview")
def preview(
    body: PreviewBody,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Run preflight. Returns verdict + single-use token.

    No AWS calls here — preview is safe to run even when the kill switch
    is off (in fact, that's the expected way to test plumbing without
    risk). The token it returns will itself fail on /execute if the
    kill switch is still off.
    """
    user = get_user_from_request(request, db)
    assert user is not None  # _require_owner already enforced

    try:
        result = firmware_preflight.run_preflight(
            db,
            release_id=body.release_id,
            cohort=body.cohort,
            device_ids=body.device_ids or None,
            macs=body.macs or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    settings = get_settings()
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.firmware_ota_preview_token_ttl_minutes
    )

    db.add(
        FirmwareDeployPreviewToken(
            token=token,
            release_id=body.release_id,
            cohort=body.cohort,
            device_ids_json=[d.device_id for d in result.devices],
            preflight_results_json=result.to_dict(),
            created_by=(user.email or "").lower(),
            expires_at=expires_at,
        )
    )
    db.commit()

    release = db.get(FirmwareRelease, body.release_id)
    return {
        "token": token,
        "expires_at": expires_at.isoformat(),
        "confirmation_required_text": release.version if release else "",
        "preflight": result.to_dict(),
        "kill_switch_enabled": settings.firmware_ota_enabled,
    }


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------


@router.post("/execute")
def execute(
    body: ExecuteBody,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    user = get_user_from_request(request, db)
    assert user is not None

    token_row = db.get(FirmwareDeployPreviewToken, body.preview_token)
    if token_row is None:
        raise HTTPException(status_code=400, detail="unknown preview token")
    if token_row.consumed_at is not None:
        raise HTTPException(status_code=400, detail="preview token already used")
    now = datetime.now(timezone.utc)
    expires_at = token_row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        raise HTTPException(status_code=400, detail="preview token expired — run /preview again")

    release = db.get(FirmwareRelease, token_row.release_id)
    if release is None:
        raise HTTPException(status_code=400, detail="release no longer exists")

    if (body.confirm_version_typed or "").strip() != (release.version or "").strip():
        raise HTTPException(
            status_code=400,
            detail=f"confirm_version_typed must exactly equal {release.version!r}",
        )

    # Re-run preflight with fresh telemetry — device state could have
    # changed in the 10-minute token window. The token locked the *set*
    # of devices, not their states.
    try:
        result = firmware_preflight.run_preflight(
            db,
            release_id=token_row.release_id,
            cohort=token_row.cohort,  # type: ignore[arg-type]
            device_ids=list(token_row.device_ids_json or []),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if token_row.cohort == "gamma" and body.override_device_ids:
        raise HTTPException(
            status_code=400,
            detail="Gamma deploys do not allow override_device_ids — every device must pass preflight",
        )
    deployable = result.deployable_device_ids(overrides=body.override_device_ids)

    if not deployable:
        raise HTTPException(
            status_code=400,
            detail="no devices pass preflight after overrides",
        )

    firmware_guardrails.check_batch_cap(len(deployable))
    firmware_guardrails.check_rate_limit(db, initiated_by=(user.email or "").lower())

    breaker = firmware_guardrails.evaluate_circuit_breaker(db)
    if breaker:
        firmware_guardrails.trip_kill_switch(breaker)
        raise HTTPException(status_code=503, detail=breaker)

    # Compose job document. target_controller_model defaults to whatever
    # the release pinned; if unset, we fall back to the first device's
    # model (homogeneous cohorts are the norm).
    target_model = (release.target_controller_model or "").lower()
    if not target_model:
        for d in result.devices:
            if d.device_id in deployable and d.controller_model:
                target_model = d.controller_model
                break
    if not target_model:
        raise HTTPException(
            status_code=400,
            detail="target_controller_model unknown on both release and devices — refusing to guess",
        )

    job_id = _compose_job_id(release.version, token_row.cohort, token_row.token)
    document = firmware_ota.JobDocument(
        version=release.version,
        url=release.binary_url or "",
        sha256=release.binary_sha256 or "",
        size=release.binary_size_bytes or 0,
        expected_model=target_model,
        model_override=False,
    )

    try:
        aws_result = firmware_ota.create_job(
            job_id=job_id,
            device_ids=deployable,
            document=document,
            description=f"Spider Grills OTA {release.version} → {token_row.cohort}",
        )
    except firmware_ota.OtaDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except firmware_ota.OtaConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:  # boto errors land here
        logger.exception("create_job failed")
        raise HTTPException(status_code=502, detail=f"AWS IoT create_job failed: {exc}")

    # Mark token consumed and write one deploy_log row per device.
    token_row.consumed_at = now

    override_set = set(body.override_device_ids or [])
    override_reasons_by_device: dict[str, list[str]] = {}
    verdict_by_device: dict[str, dict[str, Any]] = {d.device_id: d.to_dict() for d in result.devices}
    for d in result.devices:
        if d.device_id in override_set and d.soft_block_reasons:
            override_reasons_by_device[d.device_id] = list(d.soft_block_reasons)

    for device_id in deployable:
        v = verdict_by_device.get(device_id, {})
        db.add(
            FirmwareDeployLog(
                release_id=release.id,
                device_id=device_id,
                mac=v.get("mac"),
                cohort=token_row.cohort,
                initiated_by=(user.email or "").lower(),
                aws_job_id=aws_result.get("job_id"),
                status="pending",
                target_version=release.version,
                prior_version=v.get("current_version"),
                preflight_results_json=v,
                override_reasons_json={
                    "reason": body.override_reason or "",
                    "device_reasons": override_reasons_by_device.get(device_id, []),
                },
                aws_response_json=aws_result,
                queued_at=now,
                confirmed_at=now,
            )
        )

    db.commit()

    return {
        "ok": True,
        "aws_job_id": aws_result.get("job_id"),
        "deployed_device_ids": deployable,
        "skipped_device_count": len(result.devices) - len(deployable),
        "preflight": result.to_dict(),
    }


def _compose_job_id(version: str, cohort: str, token: str) -> str:
    """Deterministic enough to be idempotent on retries within a token,
    unique enough to not collide with an earlier token on the same
    release/cohort. AWS IoT job id must match ``[a-zA-Z0-9_-]{1,64}``."""
    safe_version = "".join(c for c in version if c.isalnum() or c in "-_")
    short_token = token[:16].replace("-", "").replace("_", "")
    return f"sg-ota-{safe_version}-{cohort}-{short_token}"[:64]


# ---------------------------------------------------------------------------
# Status polling + abort
# ---------------------------------------------------------------------------


@router.get("/status/{aws_job_id}")
def status(aws_job_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    rows: list[FirmwareDeployLog] = (
        db.query(FirmwareDeployLog)
        .filter(FirmwareDeployLog.aws_job_id == aws_job_id)
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail="unknown aws_job_id")

    per_device: list[dict[str, Any]] = []
    for row in rows:
        try:
            aws_state = firmware_ota.describe_job_execution(
                job_id=aws_job_id, device_id=row.device_id
            )
        except firmware_ota.OtaDisabledError:
            aws_state = {"status": "UNKNOWN", "reason": "kill switch off"}
        except Exception as exc:  # log but don't abort the batch
            logger.exception("describe_job_execution failed for %s/%s", aws_job_id, row.device_id)
            aws_state = {"status": "UNKNOWN", "error": str(exc)}

        new_status = _map_aws_status(aws_state.get("status"))
        if new_status and new_status != row.status:
            row.status = new_status
            if new_status in ("succeeded", "failed", "rolled_back", "aborted"):
                row.finished_at = datetime.now(timezone.utc)

        per_device.append({
            "device_id": row.device_id,
            "mac": row.mac,
            "dashboard_status": row.status,
            "aws": aws_state,
            "target_version": row.target_version,
            "prior_version": row.prior_version,
        })

    db.commit()
    return {
        "aws_job_id": aws_job_id,
        "devices": per_device,
    }


def _map_aws_status(aws_status: Optional[str]) -> Optional[str]:
    """Translate AWS IoT Jobs execution status to our dashboard vocabulary.

    AWS statuses: QUEUED, IN_PROGRESS, SUCCEEDED, FAILED, TIMED_OUT,
    REJECTED, REMOVED, CANCELED. Our vocabulary keeps the UI terse.
    """
    if not aws_status:
        return None
    mapping = {
        "QUEUED": "pending",
        "IN_PROGRESS": "in_flight",
        "SUCCEEDED": "succeeded",
        "FAILED": "failed",
        "TIMED_OUT": "failed",
        "REJECTED": "failed",
        "CANCELED": "aborted",
        "REMOVED": "aborted",
        "NOT_FOUND": None,  # leave the row alone — AWS lost track, human investigates
    }
    return mapping.get(aws_status)


@router.post("/abort")
def abort(body: AbortBody, db: Session = Depends(db_session)) -> dict[str, Any]:
    try:
        result = firmware_ota.cancel_job(job_id=body.aws_job_id, reason=body.reason)
    except firmware_ota.OtaDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AWS cancel_job failed: {exc}")

    now = datetime.now(timezone.utc)
    db.query(FirmwareDeployLog).filter(
        FirmwareDeployLog.aws_job_id == body.aws_job_id,
        FirmwareDeployLog.status.in_(["pending", "in_flight"]),
    ).update(
        {"status": "aborted", "finished_at": now, "error_message": body.reason},
        synchronize_session=False,
    )
    db.commit()

    return {"ok": True, "aws": result}


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


@router.get("/log")
def deploy_log(
    db: Session = Depends(db_session),
    release_id: Optional[int] = None,
    aws_job_id: Optional[str] = None,
    cohort: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    q = db.query(FirmwareDeployLog)
    if release_id is not None:
        q = q.filter(FirmwareDeployLog.release_id == release_id)
    if aws_job_id:
        q = q.filter(FirmwareDeployLog.aws_job_id == aws_job_id)
    if cohort:
        q = q.filter(FirmwareDeployLog.cohort == cohort)
    q = q.order_by(desc(FirmwareDeployLog.created_at))

    total = q.with_entities(func.count(FirmwareDeployLog.id)).scalar() or 0
    rows = q.offset(max(offset, 0)).limit(max(1, min(limit, 500))).all()

    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "rows": [_serialize_log_row(r) for r in rows],
    }


def _serialize_log_row(r: FirmwareDeployLog) -> dict[str, Any]:
    return {
        "id": r.id,
        "release_id": r.release_id,
        "device_id": r.device_id,
        "mac": r.mac,
        "cohort": r.cohort,
        "initiated_by": r.initiated_by,
        "aws_job_id": r.aws_job_id,
        "status": r.status,
        "target_version": r.target_version,
        "prior_version": r.prior_version,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "queued_at": r.queued_at.isoformat() if r.queued_at else None,
        "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "error_message": r.error_message,
    }


# ---------------------------------------------------------------------------
# Release approval
# ---------------------------------------------------------------------------


@router.post("/releases/{release_id}/approve")
def approve_release(
    release_id: int,
    body: ApproveBody,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    release = db.get(FirmwareRelease, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="release not found")
    user = get_user_from_request(request, db)
    assert user is not None

    field = f"approved_for_{body.cohort}"
    setattr(release, field, bool(body.approve))

    entry = {
        "at": datetime.now(timezone.utc).isoformat(),
        "by": (user.email or "").lower(),
        "cohort": body.cohort,
        "approve": bool(body.approve),
        "notes": body.notes or "",
    }
    audit = list(release.approval_audit_json or [])
    audit.append(entry)
    release.approval_audit_json = audit
    db.commit()

    return {
        "ok": True,
        "release_id": release.id,
        "approved_for_alpha": release.approved_for_alpha,
        "approved_for_beta": release.approved_for_beta,
        "approved_for_gamma": release.approved_for_gamma,
        "approval_audit_json": release.approval_audit_json,
    }
