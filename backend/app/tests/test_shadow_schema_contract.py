from __future__ import annotations

from typing import Any

import pytest

from app.agent.schemas import ToolDecision
from app.agent.shadow_reasoner import (
    ShadowReasoner,
    build_reasoner_decision_json_schema,
    validate_shadow_decision_schema,
)
from app.config import get_settings


def test_reasoner_decision_schema_is_strict() -> None:
    schema = build_reasoner_decision_json_schema()
    assert schema["strict"] is True
    assert schema["name"] == "pipi_reasoner_decision"
    assert schema["schema"]["discriminator"]["propertyName"] == "type"


def test_shadow_schema_validation_rejects_extra_fields() -> None:
    with pytest.raises(ValueError):
        validate_shadow_decision_schema(
            {
                "type": "answer",
                "message": "ok",
                "ui_events": [],
                "data": {},
                "debug": "not allowed",
            }
        )


def test_mock_shadow_schema_valid(run_async: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        _set_shadow_env(monkeypatch, provider="mock_shadow")
        result = await ShadowReasoner().run_shadow(
            {"user_message": "你好"},
            ToolDecision(tool_name="search_knowledge", tool_args={}, reason="test"),
        )
        assert result.status == "success"
        assert result.schema_enforced is True
        assert result.raw_mode == "mock"
        assert result.normalized_decision is not None

    run_async(scenario)


def test_mock_shadow_schema_error_is_invalid(run_async: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        _set_shadow_env(monkeypatch, provider="mock_shadow_schema_error")
        result = await ShadowReasoner().run_shadow(
            {"user_message": "你好"},
            ToolDecision(tool_name="search_knowledge", tool_args={}, reason="test"),
        )
        assert result.status == "schema_error"
        assert result.schema_enforced is True
        assert result.raw_mode == "mock"

    run_async(scenario)


def test_openai_missing_key_disables_shadow(run_async: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        _set_shadow_env(monkeypatch, provider="openai", api_key="")
        result = await ShadowReasoner().run_shadow(
            {"user_message": "你好"},
            ToolDecision(tool_name="search_knowledge", tool_args={}, reason="test"),
        )
        assert result.status == "disabled"
        assert result.enabled is False

    run_async(scenario)


def test_openai_structured_output_falls_back_to_json_object(
    run_async: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_payloads: list[dict[str, Any]] = []

    class FakeResponse:
        def __init__(self, status_code: int, text: str) -> None:
            self.status_code = status_code
            self.text = text

        def json(self) -> dict[str, Any]:
            return {"choices": [{"message": {"content": '{"type":"answer","message":"ok","ui_events":[],"data":{}}'}}]}

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, _url: str, *, headers: dict[str, str], json: dict[str, Any]) -> FakeResponse:
            captured_payloads.append(json)
            if len(captured_payloads) == 1:
                return FakeResponse(400, "response_format json_schema is not supported")
            return FakeResponse(200, "{}")

    async def scenario() -> None:
        _set_shadow_env(monkeypatch, provider="openai", api_key="test-shadow-key")
        monkeypatch.setattr("app.agent.shadow_reasoner.httpx.AsyncClient", FakeClient)
        result = await ShadowReasoner().run_shadow(
            {"user_message": "你好"},
            ToolDecision(tool_name="search_knowledge", tool_args={}, reason="test"),
        )
        assert result.status == "success"
        assert result.schema_enforced is False
        assert result.raw_mode == "json_object_fallback"
        assert captured_payloads[0]["response_format"]["type"] == "json_schema"
        assert captured_payloads[1]["response_format"]["type"] == "json_object"

    run_async(scenario)


def _set_shadow_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider: str,
    api_key: str = "",
) -> None:
    monkeypatch.setenv("LLM_SHADOW_ENABLED", "true")
    monkeypatch.setenv("LLM_PROVIDER", provider)
    monkeypatch.setenv("LLM_MODEL", "mock-shadow-v0")
    monkeypatch.setenv("OPENAI_API_KEY", api_key)
    get_settings.cache_clear()
