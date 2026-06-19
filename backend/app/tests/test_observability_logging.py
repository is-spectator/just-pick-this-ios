from __future__ import annotations

import logging

from fastapi.testclient import TestClient

from app.main import create_app


def test_response_includes_request_id_header() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health/live", headers={"X-Request-ID": "pytest-request-id"})
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "pytest-request-id"
    assert response.headers["x-pipi-runtime"] == "hybrid-harness"


def test_request_log_has_structured_fields_without_authorization(caplog) -> None:
    caplog.set_level(logging.INFO, logger="pipi.request")
    with TestClient(create_app()) as client:
        response = client.get(
            "/health/live",
            headers={"X-Request-ID": "log-request-id", "Authorization": "Bearer secret-value"},
        )
    assert response.status_code == 200
    records = [record for record in caplog.records if record.name == "pipi.request"]
    assert records
    payload = records[-1].pipi_log
    assert payload["request_id"] == "log-request-id"
    assert payload["path"] == "/health/live"
    assert payload["status_code"] == 200
    assert "latency_ms" in payload
    assert "secret-value" not in str(payload)
