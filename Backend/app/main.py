"""FastAPI application entry point."""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings

logger = logging.getLogger(__name__)


def create_application() -> FastAPI:
    """Create and configure the FastAPI application."""
    if settings.app_env.lower() == "development":
        logger.info(
            "Development database configuration: host=%s port=%s name=%s user=%s env_file_loaded=%s",
            settings.mysql_host,
            settings.mysql_port,
            settings.mysql_database,
            settings.mysql_user,
            settings.env_file_loaded,
        )

    application = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        version="0.1.0",
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(api_router, prefix=settings.api_v1_prefix)

    @application.get("/", tags=["system"])
    def root() -> dict[str, str]:
        """Provide a small discovery endpoint for the service."""
        return {"message": f"Welcome to {settings.app_name}"}

    @application.middleware("http")
    async def add_no_cache_headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(settings.api_v1_prefix):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    return application


app = create_application()
