from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.services import eval_runtime, smoke_runtime


@pytest.fixture(autouse=True)
def deterministic_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPI_MODEL_PROVIDER", "deterministic")
    monkeypatch.setenv("PIPI_CARD_COMPOSER", "deterministic")
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "disabled")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _chat(
    *,
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    client_context: dict[str, Any],
    device_uid: str = "guardrail-device",
    message: str = "你好",
) -> dict[str, Any]:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/chat/turn",
            json={
                "device_uid": device_uid,
                "message": message,
                "client_context": client_context,
            },
        )
    assert response.status_code == 200, response.text
    return response.json()


def _bypass_response(label: str) -> dict[str, Any]:
    return {
        "conversation_id": f"{label}-conversation",
        "turn_id": f"{label}-turn",
        "assistant_message": label,
        "response_kind": "chitchat",
        "location_state": "unknown",
        "ui_events": [],
        "data": {},
        "cards": [],
        "help_cards": [],
        "light_events": [],
        "tool_calls": [],
        "metadata": {},
    }


def test_regular_chat_turn_does_not_enter_eval_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        eval_runtime,
        "run_eval_chat_turn",
        lambda payload: pytest.fail("regular chat must use product runtime"),
    )

    body = _chat(
        monkeypatch=monkeypatch,
        env={"PIPI_EVAL_MODE": "true", "ALLOW_EVAL_BYPASS": "false"},
        client_context={"source": "pipi-eval-lab", "include_debug": True},
        device_uid="eval-regular-without-bypass",
    )

    assert body["metadata"]["runtime_path"] == "product"
    assert body["ui_events"] == []


def test_benchmark_like_payload_without_explicit_opt_in_uses_product_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        eval_runtime,
        "run_eval_chat_turn",
        lambda payload: pytest.fail("benchmark-looking payload needs explicit opt-in"),
    )

    body = _chat(
        monkeypatch=monkeypatch,
        env={"PIPI_EVAL_MODE": "true", "ALLOW_EVAL_BYPASS": "true"},
        client_context={
            "source": "pipi-eval-lab",
            "benchmark_suite_id": "food_beijing_onsite_v1",
            "benchmark_case_id": "guardrail",
            "eval_run_id": "pytest",
            "include_debug": True,
            "mode": "remote_smoke",
        },
        device_uid="eval-benchmark-looking-no-opt-in",
    )

    assert body["metadata"]["runtime_path"] == "product"


def test_explicit_eval_opt_in_and_allow_eval_bypass_use_eval_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(eval_runtime, "run_eval_chat_turn", lambda payload: _bypass_response("eval"))

    body = _chat(
        monkeypatch=monkeypatch,
        env={"PIPI_EVAL_MODE": "true", "ALLOW_EVAL_BYPASS": "true"},
        client_context={
            "source": "pipi-eval-lab",
            "benchmark_suite_id": "food_beijing_onsite_v1",
            "benchmark_case_id": "guardrail",
            "eval_run_id": "pytest",
            "pipi_eval_mode": True,
        },
        device_uid="eval-explicit-opt-in",
    )

    assert body["assistant_message"] == "eval"
    assert body["metadata"]["runtime_path"] == "eval_bypass"


def test_allow_eval_bypass_false_blocks_explicit_eval_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        eval_runtime,
        "run_eval_chat_turn",
        lambda payload: pytest.fail("allow_eval_bypass=false must block eval bypass"),
    )

    body = _chat(
        monkeypatch=monkeypatch,
        env={"PIPI_EVAL_MODE": "true", "ALLOW_EVAL_BYPASS": "false"},
        client_context={"source": "pipi-eval-lab", "pipi_eval_mode": True},
        device_uid="eval-explicit-but-disabled",
    )

    assert body["metadata"]["runtime_path"] == "product"


def test_explicit_smoke_opt_in_and_allow_eval_bypass_use_smoke_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke_runtime, "run_smoke_chat_turn", lambda payload: _bypass_response("smoke"))

    body = _chat(
        monkeypatch=monkeypatch,
        env={"PIPI_EVAL_MODE": "false", "ALLOW_EVAL_BYPASS": "true"},
        client_context={"source": "manual", "mode": "remote_smoke", "pipi_eval_mode": True},
        device_uid="manual-smoke-explicit-opt-in",
    )

    assert body["assistant_message"] == "smoke"
    assert body["metadata"]["runtime_path"] == "smoke_bypass"
