from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_health_live_is_static_ok() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_health_ready_reports_unready_without_database_url() -> None:
    app = create_app(Settings(_env_file=None, APP_ENV="development", DATABASE_URL=None))
    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["detail"]["database"] == "missing_database_url"


def test_health_keeps_existing_contract() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["service"] == "just-pick-this-ios-backend"
