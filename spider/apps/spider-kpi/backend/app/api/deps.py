from collections.abc import Generator
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.routes.auth import COOKIE_NAME, verify_session_token
from app.core.config import get_settings
from app.db.session import get_db
from app.services.access_control import can_write


settings = get_settings()


def db_session() -> Generator[Session, None, None]:
    yield from get_db()


def require_auth(x_app_password: str | None = Header(default=None, alias="X-App-Password")) -> None:
    if settings.auth_disabled:
        return
    if not settings.app_password or settings.app_password == "change-me":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    if x_app_password != settings.app_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def require_dashboard_session(request: Request) -> None:
    if settings.auth_disabled:
        return
    token = request.cookies.get(COOKIE_NAME)
    if not verify_session_token(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Dashboard session required")


def _session_role(request: Request) -> Optional[str]:
    if settings.auth_disabled:
        return None
    token = request.cookies.get(COOKIE_NAME)
    payload = verify_session_token(token)
    if not payload:
        return None
    return payload.get("role") or ("admin" if payload.get("is_admin") else "editor")


def require_editor(request: Request) -> None:
    """Gate an endpoint behind write-capable roles (admin or editor).

    Viewers are 403'd. Apply to any route that mutates state — firmware
    deploy, lore events, deci log entries, etc. Defense-in-depth; the UI
    also hides mutation affordances for viewers.
    """
    if settings.auth_disabled:
        return
    token = request.cookies.get(COOKIE_NAME)
    payload = verify_session_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Dashboard session required")
    role = payload.get("role") or ("admin" if payload.get("is_admin") else "editor")
    if not can_write(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is view-only.",
        )
