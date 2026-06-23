from __future__ import annotations

from typing import Any

from app.agent.pipi_loop import PipiLoop, PipiState
from app.agent.reasoner import OpenAIReasoner
from app.config import Settings, get_settings, use_request_settings


def _openai_state(message: str = "你好") -> PipiState:
    return PipiState(
        conversation_id="00000000-0000-0000-0000-000000000001",
        turn_id="00000000-0000-0000-0000-000000000002",
        user_message=message,
        allowed_tools=[],
        metadata={},
    )


def _set_openai_provider(monkeypatch: Any, *, api_key: str | None = "test-key") -> None:
    monkeypatch.setenv("PIPI_MODEL_PROVIDER", "openai")
    monkeypatch.setenv("LLM_SHADOW_ENABLED", "false")
    if api_key is None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("OPENAI_API_KEY", api_key)
    get_settings.cache_clear()


def test_openai_reasoner_missing_key_uses_deterministic_decision(
    run_async: Any,
    monkeypatch: Any,
) -> None:
    _set_openai_provider(monkeypatch, api_key=None)

    async def scenario() -> None:
        settings = Settings(
            _env_file=None,
            PIPI_MODEL_PROVIDER="openai",
            LLM_SHADOW_ENABLED=False,
            OPENAI_API_KEY=None,
        )
        with use_request_settings(settings):
            decision = await OpenAIReasoner().next(_openai_state())
        payload = decision.model_dump(mode="json")

        assert payload["type"] == "answer"
        assert payload["llm_provider"] == "openai"
        assert payload["llm_status"] == "disabled"
        assert payload["llm_fallback"] is True
        assert payload["llm_error_type"] == "disabled"

    try:
        run_async(scenario)
    finally:
        get_settings.cache_clear()


def test_openai_provider_error_records_fallback_event_without_changing_answer(
    run_async: Any,
    monkeypatch: Any,
) -> None:
    _set_openai_provider(monkeypatch, api_key="test-key")

    async def fail_openai_reasoner(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("upstream provider unavailable")

    monkeypatch.setattr("app.agent.reasoner._call_openai_reasoner", fail_openai_reasoner)

    async def scenario() -> None:
        result = await PipiLoop(reasoner=OpenAIReasoner()).run(_openai_state())

        assert result.message.startswith("你好")
        assert result.ui_events == []
        fallback_events = [
            event for event in result.trace if event.get("event") == "reasoner_provider_fallback"
        ]
        assert fallback_events
        payload = fallback_events[0]["data"]
        assert payload["provider"] == "openai"
        assert payload["status"] == "fallback"
        assert payload["error_type"] == "provider_error"
        assert payload["product_output_unchanged"] is True
        summary = result.state["reasoner_provider_fallback_summary"]
        assert summary["fallbacks"] == 1
        assert summary["provider_errors"] == 1

    try:
        run_async(scenario)
    finally:
        get_settings.cache_clear()


def test_openai_schema_error_records_fallback_event_without_changing_tools(
    run_async: Any,
    monkeypatch: Any,
) -> None:
    _set_openai_provider(monkeypatch, api_key="test-key")

    async def invalid_openai_reasoner(**_kwargs: Any) -> dict[str, Any]:
        return {"type": "tool", "tool_args": {}, "reason": "missing tool name"}

    monkeypatch.setattr("app.agent.reasoner._call_openai_reasoner", invalid_openai_reasoner)

    async def scenario() -> None:
        state = _openai_state("我现在在大同喜晋道，不知道吃什么，给我推荐一个。").model_copy(
            update={
                "allowed_tools": [
                    "search_knowledge",
                    "create_recommendation_card",
                    "draft_help_card",
                ],
            }
        )
        result = await PipiLoop(reasoner=OpenAIReasoner(), max_iters=1).run(state)

        tool_call = next(event for event in result.trace if event.get("event") == "tool_call")
        assert tool_call["data"]["tool_name"] == "search_knowledge"
        fallback = next(
            event for event in result.trace if event.get("event") == "reasoner_provider_fallback"
        )
        assert fallback["data"]["error_type"] == "schema_error"
        summary = result.state["reasoner_provider_fallback_summary"]
        assert summary["schema_errors"] == 1
        assert summary["product_output_unchanged"] is True

    try:
        run_async(scenario)
    finally:
        get_settings.cache_clear()
