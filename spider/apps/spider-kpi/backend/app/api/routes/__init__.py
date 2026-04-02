from app.api.routes.admin import router as admin_router
from app.api.routes.health import router as health_router
from app.api.routes.overview import router as overview_router

__all__ = ["admin_router", "health_router", "overview_router"]
