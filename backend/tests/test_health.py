from fastapi.testclient import TestClient

from app.main import create_app


def test_health() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_v1_health() -> None:
    client = TestClient(create_app())

    response = client.get("/v1/health")

    assert response.status_code == 404
