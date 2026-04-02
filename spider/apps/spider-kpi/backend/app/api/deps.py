from collections.abc import Generator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db


settings = get_settings()


def db_session() -> Generator[Session, None, None]:
    yield from get_db()


def require_auth(x_app_password: str | None = Header(default=None, alias="X-App-Password")) -> None:
    if settings.auth_disabled:
        return
    if x_app_password != settings.app_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
