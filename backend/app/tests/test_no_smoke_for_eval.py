from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.services import smoke_runtime


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("PIPI_EVAL_MODE", "false")
    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    get_settings.cache_clear()


def test_pipi_eval_lab_payload_never_uses_smoke_runtime(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke_runtime,
        "run_smoke_chat_turn",
        lambda payload: pytest.fail("pipi-eval-lab must exercise the real system runtime, not smoke"),
    )

    response = client.post(
        "/v1/chat/turn",
        json={
            "device_uid": "eval-remote-no-smoke-regression",
            "conversation_id": None,
            "message": "我在四季民福，哪个菜最好吃",
            "client_context": {
                "source": "pipi-eval-lab",
                "benchmark_suite_id": "pipi_system_ground_truth_100_v1",
                "benchmark_case_id": "no_smoke_regression",
                "eval_run_id": "pytest",
                "include_debug": True,
                "mode": "remote_smoke",
            },
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cards"], body
    assert body["cards"][0]["title"] == "烤鸭 + 清爽配菜 + 甜品"
    assert body["help_cards"] == []
