from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.admin import router as admin_router
from app.api import api_router
from app.config import Settings, get_settings, use_request_settings
from app.debug import router as debug_router
from app.harness.middleware import install_hybrid_harness_middleware
from app.ops import router as ops_router
from app.schemas.health import HealthResponse


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the FastAPI application."""

    has_explicit_settings = settings is not None
    resolved_settings = settings or get_settings()
    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        debug=resolved_settings.debug,
    )
    app.state.settings = resolved_settings
    _assert_startup_runtime_guards(resolved_settings)
    install_hybrid_harness_middleware(app)

    if has_explicit_settings:
        @app.middleware("http")
        async def explicit_settings_middleware(request: Request, call_next: Any) -> Any:
            with use_request_settings(resolved_settings):
                return await call_next(request)

    @app.exception_handler(SQLAlchemyError)
    async def database_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        del request
        return _database_unavailable_response(exc)

    @app.exception_handler(RuntimeError)
    async def runtime_exception_handler(request: Request, exc: RuntimeError) -> JSONResponse:
        del request
        if _is_database_config_error(exc):
            return _database_unavailable_response(exc)
        raise exc

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    async def health() -> HealthResponse:
        return {
            "ok": True,
            "service": "just-pick-this-ios-backend",
            "version": resolved_settings.app_version,
            "env": resolved_settings.app_env,
            "eval_mode": resolved_settings.pipi_eval_mode,
        }

    @app.get("/health/live", tags=["health"])
    async def health_live() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/health/ready", tags=["health"])
    async def health_ready() -> dict[str, Any]:
        status = _readiness_status(resolved_settings)
        if not status["ok"]:
            raise HTTPException(status_code=503, detail=status)
        return status

    app.include_router(api_router)
    if resolved_settings.enable_admin_routes:
        app.include_router(admin_router)
        app.include_router(ops_router)
    if resolved_settings.enable_debug_routes:
        app.include_router(debug_router)

    return app


def _assert_startup_runtime_guards(settings: Settings) -> None:
    if (
        settings.app_env in {"production", "staging"}
        and settings.langgraph_checkpoint_required
    ):
        raise RuntimeError("LANGGRAPH_CHECKPOINT_REQUIRED must be false in production/staging for V0")


def _database_unavailable_response(exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "detail": {
                "code": "database_unavailable",
                "message": "Database is unavailable. Please check DATABASE_URL and database readiness.",
                "error": exc.__class__.__name__,
            }
        },
    )


def _is_database_config_error(exc: RuntimeError) -> bool:
    return "DATABASE_URL is required" in str(exc)


app = create_app()


def _readiness_status(settings: Settings) -> dict[str, Any]:
    checks: dict[str, Any] = {
        "ok": True,
        "database": "not_configured",
        "migrations": "not_checked",
        "checkpoint": "not_required",
        "config": "ok",
    }
    if settings.database_url is None:
        checks.update({"ok": False, "database": "missing_database_url"})
        return checks
    try:
        engine = create_engine(str(settings.database_url), pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("select 1"))
            checks["database"] = "ok"
            migration_status = _migration_status(connection)
            checks["migrations"] = migration_status
            if migration_status != "ok":
                checks["ok"] = False
    except SQLAlchemyError as exc:
        checks.update({"ok": False, "database": "error", "error": exc.__class__.__name__})
        return checks
    except Exception as exc:
        checks.update({"ok": False, "database": "error", "error": exc.__class__.__name__})
        return checks

    if settings.langgraph_checkpoint_required:
        checks.update({"ok": False, "checkpoint": "unsupported_v0"})
    return checks


def _migration_status(connection: Any) -> str:
    try:
        from alembic.migration import MigrationContext
        from alembic.script import ScriptDirectory

        from app.db import Base

        del Base
        script = ScriptDirectory.from_config(_alembic_config())
        heads = set(script.get_heads())
        current = set(MigrationContext.configure(connection).get_current_heads())
        return "ok" if heads == current and heads else "out_of_date"
    except Exception:
        return "unknown"


def _alembic_config() -> Any:
    from pathlib import Path

    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parents[1]
    return Config(str(backend_dir / "alembic.ini"))
