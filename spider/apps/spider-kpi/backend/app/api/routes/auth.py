from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models import AuthUser
from app.services.auth import email_domain_allowed, extract_email_domain, hash_password, normalize_email, validate_password_strength, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()
COOKIE_NAME = "spider_kpi_session"
COOKIE_TTL_SECONDS = 60 * 60 * 24 * 14
JWT_ALGORITHM = "HS256"
RATE_LIMIT_WINDOW_SECONDS = 15 * 60
RATE_LIMIT_MAX_ATTEMPTS = 10
FAILED_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)


def db_session() -> Generator[Session, None, None]:
    yield from get_db()


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1)


class SignupRequest(BaseModel):
    email: str
    password: str = Field(min_length=1)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _rate_limit_key(request: Request, email: str) -> str:
    return f"{_client_ip(request)}:{normalize_email(email)}"


def _prune_attempts(key: str, now_ts: float | None = None) -> deque[float]:
    now = now_ts or time.time()
    attempts = FAILED_ATTEMPTS[key]
    while attempts and attempts[0] < now - RATE_LIMIT_WINDOW_SECONDS:
        attempts.popleft()
    return attempts


def _guard_rate_limit(request: Request, email: str) -> None:
    key = _rate_limit_key(request, email)
    attempts = _prune_attempts(key)
    if len(attempts) >= RATE_LIMIT_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts. Please wait a few minutes and try again.",
        )


def _record_failed_attempt(request: Request, email: str) -> None:
    key = _rate_limit_key(request, email)
    attempts = _prune_attempts(key)
    attempts.append(time.time())


def _clear_failed_attempts(request: Request, email: str) -> None:
    key = _rate_limit_key(request, email)
    FAILED_ATTEMPTS.pop(key, None)


def _validated_email(email: str) -> str:
    normalized = normalize_email(email)
    if not normalized or "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Enter a valid email address")
    return normalized


def _session_payload(user: AuthUser, expires_at: int) -> dict[str, Any]:
    return {
        "type": "dashboard_session",
        "sub": user.id,
        "email": user.email,
        "is_admin": bool(user.is_admin),
        "exp": expires_at,
    }


def serialize_user(user: AuthUser | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": user.id,
        "email": user.email,
        "is_admin": bool(user.is_admin),
    }


def build_session_token(user: AuthUser, expires_at: int | None = None) -> str:
    expires = expires_at or int(time.time()) + COOKIE_TTL_SECONDS
    return jwt.encode(_session_payload(user, expires), settings.jwt_secret, algorithm=JWT_ALGORITHM)


def verify_session_token(token: str | None) -> dict[str, Any] | None:
    if not token or not settings.jwt_secret or settings.jwt_secret == "change-me":
        return None
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        return None
    if payload.get("type") != "dashboard_session":
        return None
    if not payload.get("sub") or not payload.get("email"):
        return None
    return payload


def set_session_cookie(response: Response, user: AuthUser) -> None:
    secure = settings.env != "development"
    response.set_cookie(
        key=COOKIE_NAME,
        value=build_session_token(user),
        max_age=COOKIE_TTL_SECONDS,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/")
    response.headers["Cache-Control"] = "no-store"


def get_user_from_request(request: Request, db: Session) -> AuthUser | None:
    token = request.cookies.get(COOKIE_NAME)
    claims = verify_session_token(token)
    if not claims:
        return None
    user_id = str(claims.get("sub"))
    user = db.execute(select(AuthUser).where(AuthUser.id == user_id, AuthUser.is_active.is_(True))).scalar_one_or_none()
    if user is None:
        return None
    if normalize_email(user.email) != normalize_email(str(claims.get("email", ""))):
        return None
    return user


@router.get("/status")
def auth_status(request: Request, db: Session = Depends(db_session)) -> dict[str, Any]:
    if settings.auth_disabled:
        return {
            "authenticated": True,
            "auth_disabled": True,
            "allowed_domains": settings.allowed_signup_domains,
            "user": None,
        }
    user = get_user_from_request(request, db)
    return {
        "authenticated": user is not None,
        "auth_disabled": False,
        "allowed_domains": settings.allowed_signup_domains,
        "user": serialize_user(user),
    }


@router.post("/signup")
def auth_signup(payload: SignupRequest, request: Request, response: Response, db: Session = Depends(db_session)) -> dict[str, Any]:
    if settings.auth_disabled:
        return {
            "authenticated": True,
            "auth_disabled": True,
            "allowed_domains": settings.allowed_signup_domains,
            "user": None,
        }

    email = _validated_email(payload.email)
    _guard_rate_limit(request, email)

    if not email_domain_allowed(email, settings.allowed_signup_domains):
        _record_failed_attempt(request, email)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Only {', '.join(settings.allowed_signup_domains)} email addresses can create dashboard accounts",
        )

    password_error = validate_password_strength(payload.password)
    if password_error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=password_error)

    existing_user = db.execute(select(AuthUser).where(AuthUser.email == email)).scalar_one_or_none()
    if existing_user is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account already exists for that email")

    user_count = int(db.execute(select(func.count()).select_from(AuthUser)).scalar() or 0)
    user = AuthUser(
        email=email,
        email_domain=extract_email_domain(email),
        password_hash=hash_password(payload.password),
        is_active=True,
        is_admin=(user_count == 0),
        last_login_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    _clear_failed_attempts(request, email)
    set_session_cookie(response, user)
    return {
        "authenticated": True,
        "auth_disabled": False,
        "allowed_domains": settings.allowed_signup_domains,
        "user": serialize_user(user),
    }


@router.post("/login")
def auth_login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(db_session)) -> dict[str, Any]:
    if settings.auth_disabled:
        return {
            "authenticated": True,
            "auth_disabled": True,
            "allowed_domains": settings.allowed_signup_domains,
            "user": None,
        }

    email = _validated_email(payload.email)
    _guard_rate_limit(request, email)

    user = db.execute(select(AuthUser).where(AuthUser.email == email, AuthUser.is_active.is_(True))).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        _record_failed_attempt(request, email)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    _clear_failed_attempts(request, email)
    set_session_cookie(response, user)
    return {
        "authenticated": True,
        "auth_disabled": False,
        "allowed_domains": settings.allowed_signup_domains,
        "user": serialize_user(user),
    }


@router.post("/logout")
def auth_logout(response: Response) -> dict[str, Any]:
    clear_session_cookie(response)
    return {"authenticated": False, "user": None}
