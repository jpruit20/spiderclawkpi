from collections.abc import Generator

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.routes.auth import COOKIE_NAME, verify_session_token
from app.core.config import get_settings
from app.db.session import get_db


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


def require_dashboard_or_service_token(
    request: Request,
    x_app_password: str | None = Header(default=None, alias="X-App-Password"),
) -> None:
    """Combined auth — accepts either a valid dashboard session cookie
    OR a valid X-App-Password header. Used on routes another internal
    service (e.g. Shelob) needs to read server-to-server.

    APP_PASSWORD is already an admin-equivalent secret (require_auth
    uses it for /api/admin/*), so accepting it on telemetry-aggregate
    routes doesn't widen the blast radius — same secret, same trust
    level. Browser sessions keep working as before.

    SCOPED USE ONLY: apply to read-only telemetry-aggregate routes
    other services legitimately need. Do NOT use on write paths or on
    CX/marketing/admin surfaces that should stay dashboard-only.
    """
    if settings.auth_disabled:
        return
    if (
        x_app_password
        and settings.app_password
        and settings.app_password != "change-me"
        and x_app_password == settings.app_password
    ):
        return
    token = request.cookies.get(COOKIE_NAME)
    if not verify_session_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Dashboard session or X-App-Password required",
        )
