from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.core.config import get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()
COOKIE_NAME = "spider_kpi_session"
COOKIE_TTL_SECONDS = 60 * 60 * 24 * 14


class LoginRequest(BaseModel):
    password: str



def _cookie_payload(expires_at: int) -> str:
    return f"dashboard:{expires_at}"



def _sign_payload(payload: str) -> str:
    return hmac.new(settings.jwt_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()



def build_session_token(expires_at: int | None = None) -> str:
    expires = expires_at or int(time.time()) + COOKIE_TTL_SECONDS
    payload = _cookie_payload(expires)
    return f"{payload}.{_sign_payload(payload)}"



def verify_session_token(token: str | None) -> bool:
    if not token or "." not in token or not settings.jwt_secret or settings.jwt_secret == "change-me":
        return False
    payload, signature = token.rsplit(".", 1)
    expected = _sign_payload(payload)
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        scope, expires_raw = payload.split(":", 1)
        expires_at = int(expires_raw)
    except ValueError:
        return False
    if scope != "dashboard":
        return False
    return expires_at >= int(time.time())



def set_session_cookie(response: Response) -> None:
    secure = settings.env != "development"
    response.set_cookie(
        key=COOKIE_NAME,
        value=build_session_token(),
        max_age=COOKIE_TTL_SECONDS,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )



def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/")


@router.get("/status")
def auth_status(request: Request) -> dict[str, Any]:
    if settings.auth_disabled:
        return {"authenticated": True, "auth_disabled": True}
    token = request.cookies.get(COOKIE_NAME)
    return {"authenticated": verify_session_token(token), "auth_disabled": False}


@router.post("/login")
def auth_login(payload: LoginRequest, response: Response) -> dict[str, Any]:
    if settings.auth_disabled:
        return {"authenticated": True, "auth_disabled": True}
    if not settings.app_password or settings.app_password == "change-me":
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Dashboard password is not configured")
    if payload.password != settings.app_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")
    set_session_cookie(response)
    return {"authenticated": True, "auth_disabled": False}


@router.post("/logout")
def auth_logout(response: Response) -> dict[str, Any]:
    clear_session_cookie(response)
    return {"authenticated": False}
