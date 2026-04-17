from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from app.api.routes.admin import router as admin_router
from app.api.routes.ai_assistant import router as ai_router
from app.api.routes.app_side import router as app_side_router
from app.api.deps import require_auth
from app.api.routes.auth import router as auth_router
from app.api.routes.clickup import router as clickup_router, webhook_router as clickup_webhook_router
from app.api.routes.deci import router as deci_router
from app.api.routes.health import router as health_router
from app.api.routes.overview import router as overview_router
from app.api.routes.slack import router as slack_router, webhook_router as slack_webhook_router
from app.core.config import get_settings
from app.ingestion.connectors.ga4 import ga4_debug_self_check
from app.scheduler import build_scheduler
from app.webhooks.shopify import router as shopify_webhook_router


logger = logging.getLogger(__name__)

settings = get_settings()
scheduler = build_scheduler()
BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIST_DIR = BASE_DIR / "frontend" / "dist"
FRONTEND_ASSETS_DIR = FRONTEND_DIST_DIR / "assets"
FRONTEND_INDEX_FILE = FRONTEND_DIST_DIR / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.debug and not settings.auth_disabled:
        if not settings.app_password or settings.app_password == "change-me":
            raise RuntimeError("APP_PASSWORD must be set to a non-default value when auth is enabled for admin and machine routes")
        if not settings.jwt_secret or settings.jwt_secret == "change-me":
            raise RuntimeError("JWT_SECRET must be set to a non-default value in production")
    ga4_errors = settings.ga4_validation_errors()
    if any([settings.ga4_client_email, settings.ga4_project_id, settings.ga4_property_id, settings.ga4_private_key]):
        logger.warning(
            'GA4 startup config: client_email=%s project_id=%s property_id=%s',
            settings.masked_ga4_client_email(),
            settings.ga4_project_id or 'missing',
            settings.ga4_property_id or 'missing',
        )
    if ga4_errors:
        raise RuntimeError(f"{settings.ga4_invalid_message()} Details: {'; '.join(ga4_errors)}")
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request, call_next):
    response: Response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return response

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(overview_router)
app.include_router(admin_router)
app.include_router(deci_router)
app.include_router(ai_router)
app.include_router(app_side_router)
app.include_router(clickup_router)
app.include_router(clickup_webhook_router)
app.include_router(slack_router)
app.include_router(slack_webhook_router)
app.include_router(shopify_webhook_router)

if FRONTEND_ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS_DIR), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_frontend(full_path: str):
    if FRONTEND_INDEX_FILE.exists():
        return FileResponse(FRONTEND_INDEX_FILE)
    return {
        "detail": "Frontend build not found. Build the React app in frontend/ to serve the dashboard on this port.",
        "frontend_dist": str(FRONTEND_DIST_DIR),
    }


@app.get('/debug/ga4', dependencies=[Depends(require_auth)])
async def debug_ga4_direct():
    return ga4_debug_self_check()
