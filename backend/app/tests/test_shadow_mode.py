from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.config import get_settings
from app.main import create_app
from app.models import AgentRun, HelpCard, RecommendationCard, ToolCall
from app.services.runtime import session_scope

from .conftest import bootstrap, device_for_conversation, require_ready_response


DATONG_MESSAGE = "我现在在大同喜晋道，不知道吃什么，给我推荐一个。"
KOREA_MESSAGE = "韩国逛街，不去明洞，想小众"
DATONG_TOOL_SEQUENCE = ["search_knowledge", "create_recommendation_card"]
KOREA_TOOL_SEQUENCE = ["search_knowledge", "draft_help_card"]


@asynccontextmanager
async def _shadow_test_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    env: dict[str, str],
) -> AsyncIterator[AsyncClient]:
    base_env = {
        "PIPI_EVAL_MODE": "false",
        "ALLOW_EVAL_BYPASS": "false",
        "PIPI_MODEL_PROVIDER": "deterministic",
        "PIPI_CARD_COMPOSER": "deterministic",
        "WEB_SEARCH_PROVIDER": "disabled",
        "LLM_SHADOW_ENABLED": "false",
        "OPENAI_API_KEY": "",
    }
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for key, value in {**base_env, **env}.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()

    client = AsyncClient(
        transport=ASGITransport(app=create_app()),
        base_url="http://testserver",
    )
    try:
        yield client
    finally:
        await client.aclose()
        get_settings.cache_clear()


async def _chat_turn_response(
    client: AsyncClient,
    *,
    conversation_id: str,
    message: str,
) -> tuple[int, dict[str, Any]]:
    response = await client.post(
        "/v1/chat/turn",
        json={
            "conversation_id": conversation_id,
            "device_id": device_for_conversation(conversation_id),
            "message": message,
        },
    )
    return response.status_code, require_ready_response(response)


def _ordered_tool_names(body: dict[str, Any]) -> list[str]:
    return [
        str(tool.get("name") or tool.get("tool_name"))
        for tool in body.get("tool_calls", [])
        if tool.get("name") or tool.get("tool_name")
    ]


def _metadata_tool_names(body: dict[str, Any]) -> list[str]:
    return list(body.get("metadata", {}).get("loop", {}).get("tool_calls") or [])


def _ui_event_types(body: dict[str, Any]) -> list[str]:
    return [str(event.get("type")) for event in body.get("ui_events", []) if isinstance(event, dict)]


def _assert_tool_sequence(body: dict[str, Any], expected: list[str]) -> None:
    assert _ordered_tool_names(body) == expected
    assert _metadata_tool_names(body) == expected


def _assert_datong_product_output(body: dict[str, Any]) -> None:
    _assert_tool_sequence(body, DATONG_TOOL_SEQUENCE)
    assert body["response_kind"] == "recommendation_card"
    assert body["help_cards"] == []
    assert "show_recommendation_card" in _ui_event_types(body)
    assert len(body["cards"]) == 1, body
    title = str(body["cards"][0].get("title") or "")
    assert "刀削面" in title
    assert "肉丸子" in title


def _assert_korea_product_output(body: dict[str, Any]) -> None:
    _assert_tool_sequence(body, KOREA_TOOL_SEQUENCE)
    assert body["response_kind"] == "help_card_draft"
    assert body["cards"] == []
    assert "show_help_card_draft" in _ui_event_types(body)
    assert len(body["help_cards"]) == 1, body


def _agent_run_snapshot(body: dict[str, Any]) -> dict[str, Any]:
    agent_run_id = body.get("metadata", {}).get("agent_run_id")
    assert agent_run_id, body
    with session_scope() as session:
        agent_run = session.get(AgentRun, uuid.UUID(str(agent_run_id)))
        assert agent_run is not None, f"AgentRun {agent_run_id} was not persisted"
        tool_names = list(
            session.scalars(
                select(ToolCall.tool_name)
                .where(ToolCall.agent_run_id == agent_run.id)
                .order_by(ToolCall.sequence_index.asc(), ToolCall.created_at.asc())
            )
        )
        return {
            "output_json": dict(agent_run.output_json or {}),
            "tool_names": tool_names,
        }


def _conversation_counts(conversation_id: str) -> dict[str, int]:
    conversation_uuid = uuid.UUID(conversation_id)
    with session_scope() as session:
        tool_calls = session.scalar(
            select(func.count())
            .select_from(ToolCall)
            .join(AgentRun, ToolCall.agent_run_id == AgentRun.id)
            .where(AgentRun.conversation_id == conversation_uuid)
        )
        recommendation_cards = session.scalar(
            select(func.count())
            .select_from(RecommendationCard)
            .where(RecommendationCard.conversation_id == conversation_uuid)
        )
        help_cards = session.scalar(
            select(func.count()).select_from(HelpCard).where(HelpCard.conversation_id == conversation_uuid)
        )
    return {
        "tool_calls": int(tool_calls or 0),
        "recommendation_cards": int(recommendation_cards or 0),
        "help_cards": int(help_cards or 0),
    }


def _loop_trace(output_json: dict[str, Any]) -> list[dict[str, Any]]:
    trace = output_json.get("loop_trace")
    assert isinstance(trace, list), output_json
    return [event for event in trace if isinstance(event, dict)]


def _event_names(trace: list[dict[str, Any]]) -> set[str]:
    return {str(event.get("event")) for event in trace}


def _shadow_summary(output_json: dict[str, Any]) -> dict[str, Any]:
    summary = output_json.get("shadow_summary")
    assert isinstance(summary, dict), output_json
    return summary


def _install_fake_openai_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status_code: int = 200,
    content: str | None = None,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}
    response_content = content or '{"type":"answer","message":"shadow ok","ui_events":[],"data":{}}'

    class FakeOpenAIResponse:
        def __init__(self) -> None:
            self.status_code = status_code
            self.text = response_content

        def json(self) -> dict[str, Any]:
            return {"choices": [{"message": {"content": response_content}}]}

    class FakeOpenAIAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self) -> FakeOpenAIAsyncClient:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, Any],
        ) -> FakeOpenAIResponse:
            captured["url"] = url
            captured["headers"] = headers
            captured["payload"] = json
            return FakeOpenAIResponse()

    monkeypatch.setattr("app.agent.shadow_reasoner.httpx.AsyncClient", FakeOpenAIAsyncClient)
    return captured


def _require_shadow_runtime(output_json: dict[str, Any]) -> None:
    trace = _loop_trace(output_json)
    assert output_json.get("shadow_summary") is not None, output_json
    assert "shadow_reasoner_result" in _event_names(trace), output_json


def _shadow_tool_names(trace: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for event in trace:
        if event.get("event") != "shadow_reasoner_result":
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        for candidate in (
            data.get("tool_name"),
            data.get("selected_tool"),
            (data.get("decision") or {}).get("tool_name") if isinstance(data.get("decision"), dict) else None,
            (data.get("shadow_decision") or {}).get("tool_name")
            if isinstance(data.get("shadow_decision"), dict)
            else None,
            (data.get("tool_call") or {}).get("name") if isinstance(data.get("tool_call"), dict) else None,
            (data.get("tool_call") or {}).get("tool_name") if isinstance(data.get("tool_call"), dict) else None,
        ):
            if candidate:
                names.append(str(candidate))
                break
    return names


def test_shadow_disabled_by_default_keeps_datong_product_path(
    run_async: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        async with _shadow_test_client(
            monkeypatch,
            env={"LLM_SHADOW_ENABLED": "false"},
        ) as client:
            boot = await bootstrap(
                client,
                device_id=f"pytest-shadow-off-datong-{uuid.uuid4()}",
            )
            status, body = await _chat_turn_response(
                client,
                conversation_id=boot["conversation_id"],
                message=DATONG_MESSAGE,
            )

        assert status == 200
        _assert_datong_product_output(body)

        snapshot = _agent_run_snapshot(body)
        assert snapshot["tool_names"] == DATONG_TOOL_SEQUENCE
        output_json = snapshot["output_json"]
        summary = output_json.get("shadow_summary")
        assert summary is None or summary.get("enabled") is False
        assert "shadow_reasoner_result" not in _event_names(_loop_trace(output_json))

    run_async(scenario)


def test_mock_shadow_keeps_datong_product_output_and_records_shadow_result(
    run_async: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        async with _shadow_test_client(
            monkeypatch,
            env={"LLM_SHADOW_ENABLED": "true", "LLM_PROVIDER": "mock_shadow"},
        ) as client:
            boot = await bootstrap(
                client,
                device_id=f"pytest-shadow-on-datong-{uuid.uuid4()}",
            )
            status, body = await _chat_turn_response(
                client,
                conversation_id=boot["conversation_id"],
                message=DATONG_MESSAGE,
            )

        assert status == 200
        _assert_datong_product_output(body)

        snapshot = _agent_run_snapshot(body)
        assert snapshot["tool_names"] == DATONG_TOOL_SEQUENCE
        output_json = snapshot["output_json"]
        _require_shadow_runtime(output_json)
        trace = _loop_trace(output_json)
        assert "shadow_reasoner_result" in _event_names(trace)
        summary = _shadow_summary(output_json)
        assert summary.get("enabled") is True
        assert int(summary.get("calls") or 0) > 0

    run_async(scenario)


def test_mock_shadow_schema_error_does_not_affect_datong_product_path(
    run_async: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        async with _shadow_test_client(
            monkeypatch,
            env={"LLM_SHADOW_ENABLED": "true", "LLM_PROVIDER": "mock_shadow_schema_error"},
        ) as client:
            boot = await bootstrap(
                client,
                device_id=f"pytest-shadow-schema-error-datong-{uuid.uuid4()}",
            )
            status, body = await _chat_turn_response(
                client,
                conversation_id=boot["conversation_id"],
                message=DATONG_MESSAGE,
            )

        assert status == 200
        _assert_datong_product_output(body)

        output_json = _agent_run_snapshot(body)["output_json"]
        _require_shadow_runtime(output_json)
        summary = _shadow_summary(output_json)
        assert int(summary.get("schema_errors") or 0) > 0

    run_async(scenario)


def test_shadow_decision_mismatch_is_recorded_without_changing_korea_ui_events(
    run_async: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        async with _shadow_test_client(
            monkeypatch,
            env={"LLM_SHADOW_ENABLED": "true", "LLM_PROVIDER": "mock_shadow"},
        ) as client:
            boot = await bootstrap(
                client,
                device_id=f"pytest-shadow-mismatch-korea-{uuid.uuid4()}",
            )
            status, body = await _chat_turn_response(
                client,
                conversation_id=boot["conversation_id"],
                message=KOREA_MESSAGE,
            )

        assert status == 200
        _assert_korea_product_output(body)
        assert _ui_event_types(body) == ["show_help_card_draft"]

        output_json = _agent_run_snapshot(body)["output_json"]
        _require_shadow_runtime(output_json)
        trace = _loop_trace(output_json)
        assert "create_recommendation_card" in _shadow_tool_names(trace)
        summary = _shadow_summary(output_json)
        assert int(summary.get("decision_mismatches") or 0) > 0

    run_async(scenario)


def test_shadow_does_not_add_tool_calls_or_persist_cards(
    run_async: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        async with _shadow_test_client(
            monkeypatch,
            env={"LLM_SHADOW_ENABLED": "true", "LLM_PROVIDER": "mock_shadow"},
        ) as client:
            boot = await bootstrap(
                client,
                device_id=f"pytest-shadow-no-side-effects-{uuid.uuid4()}",
            )
            status, body = await _chat_turn_response(
                client,
                conversation_id=boot["conversation_id"],
                message=DATONG_MESSAGE,
            )

        assert status == 200
        _assert_datong_product_output(body)

        snapshot = _agent_run_snapshot(body)
        assert snapshot["tool_names"] == DATONG_TOOL_SEQUENCE
        _require_shadow_runtime(snapshot["output_json"])

        counts = _conversation_counts(body["conversation_id"])
        assert counts["tool_calls"] == len(DATONG_TOOL_SEQUENCE)
        assert counts["recommendation_cards"] == len(body["cards"]) == 1
        assert counts["help_cards"] == len(body["help_cards"]) == 0

    run_async(scenario)


def test_openai_shadow_provider_keeps_product_output_and_records_valid_shadow(
    run_async: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _install_fake_openai_client(monkeypatch)

    async def scenario() -> None:
        async with _shadow_test_client(
            monkeypatch,
            env={
                "LLM_SHADOW_ENABLED": "true",
                "LLM_PROVIDER": "openai",
                "LLM_MODEL": "gpt-4.1-mini",
                "OPENAI_API_KEY": "test-shadow-key",
            },
        ) as client:
            boot = await bootstrap(
                client,
                device_id=f"pytest-shadow-openai-datong-{uuid.uuid4()}",
            )
            status, body = await _chat_turn_response(
                client,
                conversation_id=boot["conversation_id"],
                message=DATONG_MESSAGE,
            )

        assert status == 200
        _assert_datong_product_output(body)

        output_json = _agent_run_snapshot(body)["output_json"]
        _require_shadow_runtime(output_json)
        summary = _shadow_summary(output_json)
        assert summary.get("provider") == "openai"
        assert summary.get("model") == "gpt-4.1-mini"
        assert int(summary.get("calls") or 0) > 0
        assert int(summary.get("schema_valid_count") or 0) > 0

        assert str(captured["url"]).endswith("/chat/completions")
        assert captured["payload"]["model"] == "gpt-4.1-mini"
        prompt_payload = str(captured["payload"])
        assert "test-shadow-key" not in prompt_payload

    run_async(scenario)


def test_openai_shadow_provider_error_does_not_affect_product_output(
    run_async: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_openai_client(monkeypatch, status_code=500, content='{"error":"temporary"}')

    async def scenario() -> None:
        async with _shadow_test_client(
            monkeypatch,
            env={
                "LLM_SHADOW_ENABLED": "true",
                "LLM_PROVIDER": "openai",
                "LLM_MODEL": "gpt-4.1-mini",
                "OPENAI_API_KEY": "test-shadow-key",
            },
        ) as client:
            boot = await bootstrap(
                client,
                device_id=f"pytest-shadow-openai-error-{uuid.uuid4()}",
            )
            status, body = await _chat_turn_response(
                client,
                conversation_id=boot["conversation_id"],
                message=DATONG_MESSAGE,
            )

        assert status == 200
        _assert_datong_product_output(body)

        output_json = _agent_run_snapshot(body)["output_json"]
        _require_shadow_runtime(output_json)
        summary = _shadow_summary(output_json)
        assert summary.get("provider") == "openai"
        assert int(summary.get("provider_errors") or 0) > 0

    run_async(scenario)


def test_openai_shadow_missing_key_is_disabled_without_network(
    run_async: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NetworkShouldNotBeCalled:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("OpenAI shadow should disable before creating an HTTP client.")

    monkeypatch.setattr("app.agent.shadow_reasoner.httpx.AsyncClient", NetworkShouldNotBeCalled)

    async def scenario() -> None:
        async with _shadow_test_client(
            monkeypatch,
            env={
                "LLM_SHADOW_ENABLED": "true",
                "LLM_PROVIDER": "openai",
                "LLM_MODEL": "gpt-4.1-mini",
            },
        ) as client:
            boot = await bootstrap(
                client,
                device_id=f"pytest-shadow-openai-missing-key-{uuid.uuid4()}",
            )
            status, body = await _chat_turn_response(
                client,
                conversation_id=boot["conversation_id"],
                message=DATONG_MESSAGE,
            )

        assert status == 200
        _assert_datong_product_output(body)

        output_json = _agent_run_snapshot(body)["output_json"]
        _require_shadow_runtime(output_json)
        summary = _shadow_summary(output_json)
        assert summary.get("provider") == "openai"
        assert int(summary.get("calls") or 0) == 0

    run_async(scenario)
