from fastapi.testclient import TestClient

from app.main import create_app


def test_health() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["service"] == "just-pick-this-ios-backend"
    assert "version" in body
    assert "env" in body
    assert "eval_mode" in body


def test_v1_health() -> None:
    client = TestClient(create_app())

    response = client.get("/v1/health")

    assert response.status_code == 404


def test_product_entry_is_chat_first() -> None:
    app = create_app()
    route_paths = {getattr(route, "path", "") for route in app.routes}

    assert "/v1/chat/turn" in route_paths
    assert "/recommend" not in route_paths
    assert "/v1/recommend" not in route_paths
