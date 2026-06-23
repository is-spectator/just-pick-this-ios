from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_chat_turn_returns_structured_503_when_database_is_unavailable() -> None:
    app = create_app(Settings(_env_file=None, ADMIN_TOKEN="admin", DATABASE_URL=None))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/chat/turn",
            json={
                "device_uid": "pytest-db-unavailable",
                "conversation_id": None,
                "message": "你好",
                "client_context": {"source": "pytest"},
            },
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "database_unavailable"
