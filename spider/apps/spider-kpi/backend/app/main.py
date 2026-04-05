from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from app.api.routes.admin import router as admin_router
from app.api.routes.health import router as health_router
from app.api.routes.overview import router as overview_router
from app.core.config import get_settings
from app.scheduler import build_scheduler
from app.webhooks.shopify import router as shopify_webhook_router


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
            raise RuntimeError("APP_PASSWORD must be set to a non-default value when auth is enabled")
        if not settings.jwt_secret or settings.jwt_secret == "change-me":
            raise RuntimeError("JWT_SECRET must be set to a non-default value in production")
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

app.include_router(health_router)
app.include_router(overview_router)
app.include_router(admin_router)
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
