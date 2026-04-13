"""AI assistant routes — chat panel → Claude Code CLI → SSE response."""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict, deque
from collections.abc import Generator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.routes.auth import COOKIE_NAME, get_user_from_request
from app.core.config import get_settings
from app.db.session import get_db
from app.models import AuthUser
from app.services.ai_scoping import get_user_divisions, resolve_scope
from app.services.ai_agent import run_cli_turn, SSEEvent
from app.services.ai_deploy import validate_and_deploy

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai", tags=["ai-assistant"])
settings = get_settings()

# ── rate limiting ──

RATE_WINDOW_SECONDS = 3600  # 1 hour
RATE_MAX_REQUESTS = 10
_request_log: dict[str, deque[float]] = defaultdict(deque)


def _check_rate_limit(email: str) -> None:
    now = time.time()
    log = _request_log[email]
    while log and log[0] < now - RATE_WINDOW_SECONDS:
        log.popleft()
    if len(log) >= RATE_MAX_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="AI assistant rate limit reached. Please wait before sending more requests.",
        )
    log.append(now)


# ── dependency ──

def db_session() -> Generator[Session, None, None]:
    yield from get_db()


def _require_user(request: Request, db: Session = Depends(db_session)) -> AuthUser:
    user = get_user_from_request(request, db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


# ── request schemas ──

class ChatMessageHistory(BaseModel):
    role: str
    content: str


class AiMessageRequest(BaseModel):
    division: str
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatMessageHistory] = Field(default_factory=list)


# ── routes ──

@router.get("/access")
def get_ai_access(user: AuthUser = Depends(_require_user)):
    """Return the divisions this user may use the AI assistant on."""
    if not getattr(settings, "ai_assistant_enabled", False):
        return {"enabled": False, "divisions": []}
    divisions = get_user_divisions(user.email, bool(user.is_admin))
    return {"enabled": True, "divisions": divisions}


@router.post("/message")
async def send_ai_message(
    body: AiMessageRequest,
    request: Request,
    db: Session = Depends(db_session),
):
    """Accept a user message, invoke Claude Code CLI, and stream SSE events."""
    if not getattr(settings, "ai_assistant_enabled", False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI assistant is not enabled.",
        )

    user = get_user_from_request(request, db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    # Access control
    scope = resolve_scope(user.email, bool(user.is_admin), body.division)
    if scope is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You do not have AI editing access to the {body.division} division.",
        )

    _check_rate_limit(user.email)

    workspace = getattr(settings, "workspace_root", ".")
    history = [{"role": m.role, "content": m.content} for m in body.history]

    async def event_stream():
        files_modified: list[str] = []
        try:
            async for sse in run_cli_turn(body.message, scope, history, workspace):
                # Track file modifications for deploy
                if sse.event == "file_modified":
                    files_modified.append(sse.data.get("file", ""))

                yield f"event: {sse.event}\ndata: {json.dumps(sse.data)}\n\n"

                # After the "done" event, trigger deploy if files changed
                if sse.event == "done" and files_modified:
                    yield f"event: status\ndata: {json.dumps({'message': 'Deploying changes...'})}\n\n"
                    try:
                        result = await validate_and_deploy(
                            scope=scope,
                            workspace_root=workspace,
                            summary=body.message[:80],
                        )
                        yield f"event: deploy\ndata: {json.dumps({'success': result.success, 'commit': result.commit_sha, 'message': result.message, 'reverted': result.reverted_files})}\n\n"
                    except Exception as deploy_err:
                        logger.exception("Deploy failed for user=%s", user.email)
                        yield f"event: deploy\ndata: {json.dumps({'success': False, 'message': str(deploy_err)})}\n\n"

        except Exception as exc:
            logger.exception("AI stream error for user=%s", user.email)
            yield f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Tell nginx not to buffer
        },
    )
