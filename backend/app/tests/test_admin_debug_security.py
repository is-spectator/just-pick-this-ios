from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import get_db_session
from app.main import create_app


def _raise_if_db_session_is_touched():
    raise AssertionError("admin auth should run before database dependencies")


def test_admin_unauthorized_does_not_touch_database() -> None:
    app = create_app(Settings(_env_file=None, ADMIN_TOKEN="secret-admin", DATABASE_URL=None))
    app.dependency_overrides[get_db_session] = _raise_if_db_session_is_touched
    with TestClient(app, raise_server_exceptions=True) as client:
        response = client.get("/admin/api/sessions")
    assert response.status_code == 401


def test_admin_requires_bearer_token_only() -> None:
    app = create_app(Settings(_env_file=None, ADMIN_TOKEN="secret-admin", DATABASE_URL=None))
    app.dependency_overrides[get_db_session] = _raise_if_db_session_is_touched
    with TestClient(app) as client:
        assert client.get("/admin/api/sessions").status_code == 401
        assert client.get("/admin/api/sessions", params={"token": "secret-admin"}).status_code == 401
        assert client.get("/admin/api/sessions", headers={"x-admin-token": "secret-admin"}).status_code == 401


def test_debug_routes_default_404() -> None:
    app = create_app(Settings(_env_file=None, ADMIN_TOKEN="admin"))
    with TestClient(app) as client:
        assert client.get("/debug/sessions").status_code == 404


def test_debug_routes_when_enabled_require_header_token() -> None:
    app = create_app(
        Settings(
            _env_file=None,
            ENABLE_DEBUG_ROUTES="true",
            DEBUG_DASHBOARD_TOKEN="debug-secret",
            ADMIN_TOKEN="admin",
        )
    )
    with TestClient(app) as client:
        assert client.get("/debug/sessions").status_code == 401
        assert client.get("/debug/sessions", params={"token": "debug-secret"}).status_code == 401
        assert client.get("/debug/sessions", headers={"x-debug-token": "debug-secret"}).status_code == 401
        assert client.get("/debug/sessions", headers={"authorization": "Bearer debug-secret"}).status_code == 200
