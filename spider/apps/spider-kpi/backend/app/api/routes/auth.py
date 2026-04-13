from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models import AuthUser, AuthVerificationChallenge
from app.services.auth import (
    email_domain_allowed,
    extract_email_domain,
    hash_password,
    normalize_email,
    validate_password_strength,
    verify_password,
)
from app.services.email_auth import (
    generate_verification_token,
    send_verification_email,
    verification_expiry,
    verification_token_hash,
)

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


class SignupRequest(BaseModel):
    email: str
    password: str = Field(min_length=1)


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1)


class ResendVerificationRequest(BaseModel):
    email: str


# ── helpers ──


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
    from app.services.ai_scoping import get_user_divisions
    ai_divisions = get_user_divisions(user.email, bool(user.is_admin))
    return {
        "id": user.id,
        "email": user.email,
        "is_admin": bool(user.is_admin),
        "ai_divisions": ai_divisions,
        "ai_enabled": bool(getattr(settings, "ai_assistant_enabled", False) and ai_divisions),
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


def _create_and_send_verification(db: Session, email: str, email_domain: str) -> None:
    """Generate a verification token, store it, and send the email."""
    token = generate_verification_token()
    challenge = AuthVerificationChallenge(
        email=email,
        email_domain=email_domain,
        token_hash=verification_token_hash(token),
        purpose='verify_email',
        expires_at=verification_expiry(),
        consumed_at=None,
    )
    db.add(challenge)
    db.commit()
    send_verification_email(email, token)


# ── routes ──


@router.get("/status")
def auth_status(request: Request, db: Session = Depends(db_session)) -> dict[str, Any]:
    if settings.auth_disabled:
        return {
            "authenticated": True,
            "auth_disabled": True,
            "allowed_domains": [],
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
def auth_signup(payload: SignupRequest, request: Request, db: Session = Depends(db_session)) -> dict[str, Any]:
    """Create a new account with email + password, then send verification email."""
    if settings.auth_disabled:
        return {"ok": True, "detail": "Authentication is currently disabled."}

    email = _validated_email(payload.email)
    _guard_rate_limit(request, email)

    # Domain restriction
    if not email_domain_allowed(email, settings.allowed_signup_domains):
        _record_failed_attempt(request, email)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Only {', '.join(settings.allowed_signup_domains)} email addresses can create accounts.",
        )

    # Password strength
    password_error = validate_password_strength(payload.password)
    if password_error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=password_error)

    # Check if user already exists
    existing = db.execute(select(AuthUser).where(AuthUser.email == email)).scalar_one_or_none()
    if existing:
        if existing.email_verified:
            # Don't reveal that account exists — just say "check your email"
            return {"ok": True, "detail": "If that email is eligible, a verification link has been sent. Check your inbox."}
        # Re-send verification for unverified existing account (update their password too)
        existing.password_hash = hash_password(payload.password)
        db.commit()
        _create_and_send_verification(db, email, extract_email_domain(email))
        _clear_failed_attempts(request, email)
        return {"ok": True, "detail": "If that email is eligible, a verification link has been sent. Check your inbox."}

    # Create new user (unverified)
    user_count = int(db.execute(select(func.count()).select_from(AuthUser)).scalar() or 0)
    user = AuthUser(
        email=email,
        email_domain=extract_email_domain(email),
        password_hash=hash_password(payload.password),
        email_verified=False,
        is_active=True,
        is_admin=(user_count == 0),
    )
    db.add(user)
    db.commit()

    # Send verification email
    _create_and_send_verification(db, email, extract_email_domain(email))
    _clear_failed_attempts(request, email)

    return {"ok": True, "detail": "If that email is eligible, a verification link has been sent. Check your inbox."}


@router.get("/verify-email")
def verify_email_link(token: str, request: Request, db: Session = Depends(db_session)):
    """Handle the verification link clicked from the email."""
    if not token or len(token) < 10:
        return RedirectResponse(url="/?verify=invalid", status_code=302)

    now = datetime.now(timezone.utc)
    token_hashed = verification_token_hash(token)
    challenge = db.execute(
        select(AuthVerificationChallenge)
        .where(
            AuthVerificationChallenge.token_hash == token_hashed,
            AuthVerificationChallenge.purpose == 'verify_email',
            AuthVerificationChallenge.consumed_at.is_(None),
            AuthVerificationChallenge.expires_at >= now,
        )
        .order_by(AuthVerificationChallenge.created_at.desc())
    ).scalars().first()

    if challenge is None:
        return RedirectResponse(url="/?verify=expired", status_code=302)

    # Find the user
    user = db.execute(select(AuthUser).where(AuthUser.email == challenge.email)).scalar_one_or_none()
    if user is None:
        return RedirectResponse(url="/?verify=invalid", status_code=302)

    # Mark challenge consumed and user verified
    challenge.consumed_at = now
    user.email_verified = True
    user.is_active = True
    db.commit()

    return RedirectResponse(url="/?verify=success", status_code=302)


@router.post("/login")
def auth_login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(db_session)) -> dict[str, Any]:
    """Sign in with email + password. Account must be verified first."""
    if settings.auth_disabled:
        return {
            "authenticated": True,
            "auth_disabled": True,
            "allowed_domains": [],
            "user": None,
        }

    email = _validated_email(payload.email)
    _guard_rate_limit(request, email)

    user = db.execute(select(AuthUser).where(AuthUser.email == email, AuthUser.is_active.is_(True))).scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.password_hash):
        _record_failed_attempt(request, email)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email address first. Check your inbox for the verification link.",
        )

    # Successful login
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    _clear_failed_attempts(request, email)
    set_session_cookie(response, user)
    return {
        "authenticated": True,
        "auth_disabled": False,
        "allowed_domains": settings.allowed_signup_domains,
        "user": serialize_user(user),
    }


@router.post("/resend-verification")
def resend_verification(payload: ResendVerificationRequest, request: Request, db: Session = Depends(db_session)) -> dict[str, Any]:
    """Re-send the verification email for an unverified account."""
    if settings.auth_disabled:
        return {"ok": True, "detail": "Authentication is currently disabled."}

    email = _validated_email(payload.email)
    _guard_rate_limit(request, email)

    user = db.execute(select(AuthUser).where(AuthUser.email == email)).scalar_one_or_none()
    if user and not user.email_verified:
        _create_and_send_verification(db, email, extract_email_domain(email))
        _clear_failed_attempts(request, email)

    # Always return the same message to avoid leaking account existence
    return {"ok": True, "detail": "If that account exists and is not yet verified, a new verification link has been sent."}


@router.post("/logout")
def auth_logout(response: Response) -> dict[str, Any]:
    clear_session_cookie(response)
    return {"authenticated": False, "user": None}


# Legacy OTP endpoints — return 410 to signal clients to update
@router.post("/request-code")
def request_code_legacy() -> None:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail="OTP codes have been replaced. Use email + password signup/login instead.")


@router.post("/verify-code")
def verify_code_legacy() -> None:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail="OTP codes have been replaced. Use email + password signup/login instead.")
