from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.config import get_settings
from app.main import create_app
from app.models import AgentRun, ToolCall
from app.services.runtime import session_scope

from .conftest import bootstrap, device_for_conversation, require_ready_response


DATONG_MESSAGE = "我现在在大同喜晋道，不知道吃什么，给我推荐一个。"


@asynccontextmanager
async def _openai_product_client(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    env = {
        "PIPI_EVAL_MODE": "false",
        "ALLOW_EVAL_BYPASS": "false",
        "PIPI_MODEL_PROVIDER": "openai",
        "PIPI_CARD_COMPOSER": "deterministic",
        "WEB_SEARCH_PROVIDER": "disabled",
        "LLM_SHADOW_ENABLED": "false",
        "OPENAI_API_KEY": "test-product-key",
        "OPENAI_MODEL": "gpt-4.1-mini",
    }
    for key, value in env.items():
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
) -> dict[str, Any]:
    response = await client.post(
        "/v1/chat/turn",
        json={
            "conversation_id": conversation_id,
            "device_id": device_for_conversation(conversation_id),
            "message": message,
        },
    )
    return require_ready_response(response)


def _install_fake_openai_reasoner(
    monkeypatch: pytest.MonkeyPatch,
    decisions: Sequence[str],
) -> dict[str, Any]:
    captured: dict[str, Any] = {"calls": []}
    queue = list(decisions)

    class FakeOpenAIResponse:
        status_code = 200
        text = "{}"

        def __init__(self, content: str) -> None:
            self._content = content

        def json(self) -> dict[str, Any]:
            return {"choices": [{"message": {"content": self._content}}]}

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
            captured["calls"].append({"url": url, "headers": headers, "payload": json})
            content = queue.pop(0) if queue else '{"type":"answer","message":"LLM 收口。","ui_events":[],"data":{}}'
            return FakeOpenAIResponse(content)

    monkeypatch.setattr("app.agent.reasoner.httpx.AsyncClient", FakeOpenAIAsyncClient)
    return captured


def _tool_names(body: dict[str, Any]) -> list[str]:
    return list(body.get("metadata", {}).get("loop", {}).get("tool_calls") or [])


def _agent_run_output(body: dict[str, Any]) -> dict[str, Any]:
    agent_run_id = body.get("metadata", {}).get("agent_run_id")
    assert agent_run_id, body
    with session_scope() as session:
        agent_run = session.get(AgentRun, uuid.UUID(str(agent_run_id)))
        assert agent_run is not None
        return dict(agent_run.output_json or {})


def _conversation_tool_count(conversation_id: str) -> int:
    with session_scope() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(ToolCall)
                .join(AgentRun, ToolCall.agent_run_id == AgentRun.id)
                .where(AgentRun.conversation_id == uuid.UUID(conversation_id))
            )
            or 0
        )


def test_openai_product_reasoner_handles_greeting_without_tools(
    run_async: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _install_fake_openai_reasoner(
        monkeypatch,
        ['{"type":"answer","message":"你好，我是皮皮。你告诉我位置和想做的事，我直接帮你选。","ui_events":[],"data":{}}'],
    )

    async def scenario() -> None:
        async with _openai_product_client(monkeypatch) as client:
            boot = await bootstrap(
                client,
                device_id=f"pytest-openai-product-greeting-{uuid.uuid4()}",
            )
            body = await _chat_turn_response(
                client,
                conversation_id=boot["conversation_id"],
                message="你好",
            )

        assert captured["calls"], "OpenAI product reasoner was not called"
        assert body["assistant_message"].startswith("你好")
        assert body["ui_events"] == []
        assert _tool_names(body) == []
        assert _conversation_tool_count(body["conversation_id"]) == 0
        output = _agent_run_output(body)
        reasoner_events = [
            event for event in output.get("loop_trace", []) if event.get("event") == "reasoner_decision"
        ]
        assert reasoner_events
        assert reasoner_events[0]["data"].get("llm_provider") == "openai"
        assert reasoner_events[0]["data"].get("llm_status") == "success"

    run_async(scenario)


def test_openai_product_reasoner_drives_datong_tool_loop(
    run_async: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _install_fake_openai_reasoner(
        monkeypatch,
        [
            '{"type":"tool","tool_name":"search_knowledge","tool_args":{},"reason":"先查证据"}',
            '{"type":"tool","tool_name":"create_recommendation_card","tool_args":{},"reason":"证据够，出卡"}',
            '{"type":"answer","message":"LLM 看完证据了，就这个。","ui_events":[],"data":{}}',
        ],
    )

    async def scenario() -> None:
        async with _openai_product_client(monkeypatch) as client:
            boot = await bootstrap(
                client,
                device_id=f"pytest-openai-product-datong-{uuid.uuid4()}",
            )
            body = await _chat_turn_response(
                client,
                conversation_id=boot["conversation_id"],
                message=DATONG_MESSAGE,
            )

        assert len(captured["calls"]) >= 3
        assert _tool_names(body) == ["search_knowledge", "create_recommendation_card"]
        assert body["response_kind"] == "recommendation_card"
        assert [event.get("type") for event in body["ui_events"]] == ["show_recommendation_card"]
        assert body["assistant_message"] == "LLM 看完证据了，就这个。"
        output = _agent_run_output(body)
        statuses = [
            event.get("data", {}).get("llm_status")
            for event in output.get("loop_trace", [])
            if event.get("event") == "reasoner_decision"
        ]
        assert statuses and set(statuses) == {"success"}
        assert "test-product-key" not in str(captured["calls"][0]["payload"])

    run_async(scenario)


def test_openai_product_reasoner_invalid_schema_falls_back_to_deterministic(
    run_async: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _install_fake_openai_reasoner(
        monkeypatch,
        [
            '{"type":"tool","tool_args":{},"reason":"missing tool name"}',
            '{"type":"tool","tool_args":{},"reason":"missing tool name"}',
            '{"type":"answer","ui_events":[],"data":{}}',
        ],
    )

    async def scenario() -> None:
        async with _openai_product_client(monkeypatch) as client:
            boot = await bootstrap(
                client,
                device_id=f"pytest-openai-product-fallback-{uuid.uuid4()}",
            )
            body = await _chat_turn_response(
                client,
                conversation_id=boot["conversation_id"],
                message=DATONG_MESSAGE,
            )

        assert captured["calls"], "OpenAI product reasoner was not called"
        assert _tool_names(body) == ["search_knowledge", "create_recommendation_card"]
        assert body["response_kind"] == "recommendation_card"
        output = _agent_run_output(body)
        fallback_statuses = [
            event.get("data", {}).get("llm_status")
            for event in output.get("loop_trace", [])
            if event.get("event") == "reasoner_decision"
        ]
        assert "fallback" in fallback_statuses
        fallback_events = [
            event
            for event in output.get("loop_trace", [])
            if event.get("event") == "reasoner_provider_fallback"
        ]
        assert fallback_events
        assert fallback_events[0].get("data", {}).get("error_type") == "schema_error"
        summary = body.get("metadata", {}).get("loop", {}).get("reasoner_provider_fallback")
        assert summary["schema_errors"] >= 1
        assert summary["schema_error_rate"] > 0
        assert summary["fallback_rate"] > 0

    run_async(scenario)
