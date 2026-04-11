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
