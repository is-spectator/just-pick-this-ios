from fastapi import FastAPI

from app.api import api_router
from app.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the FastAPI application."""

    resolved_settings = settings or get_settings()
    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        debug=resolved_settings.debug,
    )
    app.state.settings = resolved_settings

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(api_router)

    return app


app = create_app()
