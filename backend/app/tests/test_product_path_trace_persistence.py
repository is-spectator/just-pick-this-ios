from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select

from app.models import AgentRun, Question, RetrievalRun, ToolCall, Turn
from app.services.runtime import session_scope

from .conftest import bootstrap, chat_turn


REQUIRED_LOOP_EVENTS = {
    "input_gate_result",
    "context_pack",
    "reasoner_decision",
    "tool_call",
    "tool_result",
    "evaluator_result",
    "answer_gate_result",
}


def _event_names(trace: list[dict[str, Any]]) -> set[str]:
    return {str(event.get("event")) for event in trace if isinstance(event, dict)}


def _load_agent_run(agent_run_id: str) -> AgentRun:
    with session_scope() as session:
        agent_run = session.get(AgentRun, uuid.UUID(agent_run_id))
        assert agent_run is not None, f"AgentRun {agent_run_id} was not persisted"
        session.expunge(agent_run)
        return agent_run


def _loop_trace_for_response(body: dict[str, Any]) -> list[dict[str, Any]]:
    agent_run_id = body.get("metadata", {}).get("agent_run_id")
    assert agent_run_id, body

    agent_run = _load_agent_run(str(agent_run_id))
    output = agent_run.output_json
    assert isinstance(output, dict), output

    trace = output.get("loop_trace")
    assert isinstance(trace, list), output
    assert trace, output
    return trace


def _ordered_tool_names(body: dict[str, Any]) -> list[str]:
    return list(body.get("metadata", {}).get("loop", {}).get("tool_calls") or [])


def _prompt_versions(body: dict[str, Any]) -> dict[str, Any]:
    prompt_versions = body.get("metadata", {}).get("prompt_versions")
    assert isinstance(prompt_versions, dict), body.get("metadata")
    assert prompt_versions, body.get("metadata")
    return prompt_versions


def _ui_event_types(body: dict[str, Any]) -> set[str]:
    return {str(event.get("type")) for event in body.get("ui_events", []) if isinstance(event, dict)}


def _conversation_runtime_counts(conversation_id: str) -> dict[str, int]:
    conversation_uuid = uuid.UUID(conversation_id)
    with session_scope() as session:
        turn_count = session.scalar(
            select(func.count()).select_from(Turn).where(Turn.conversation_id == conversation_uuid)
        )
        question_count = session.scalar(
            select(func.count()).select_from(Question).where(Question.conversation_id == conversation_uuid)
        )
        tool_call_count = session.scalar(
            select(func.count())
            .select_from(ToolCall)
            .join(AgentRun, ToolCall.agent_run_id == AgentRun.id)
            .where(AgentRun.conversation_id == conversation_uuid)
        )
        retrieval_run_count = session.scalar(
            select(func.count())
            .select_from(RetrievalRun)
            .join(AgentRun, RetrievalRun.agent_run_id == AgentRun.id)
            .where(AgentRun.conversation_id == conversation_uuid)
        )

    return {
        "turns": int(turn_count or 0),
        "questions": int(question_count or 0),
        "tool_calls": int(tool_call_count or 0),
        "retrieval_runs": int(retrieval_run_count or 0),
    }


def _assert_full_loop_trace(body: dict[str, Any]) -> None:
    trace = _loop_trace_for_response(body)
    missing = REQUIRED_LOOP_EVENTS - _event_names(trace)
    assert not missing, {"missing_events": sorted(missing), "trace": trace}


def test_chat_turn_persists_full_loop_trace_for_datong(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        boot = await bootstrap(
            async_client,
            device_id=f"pytest-product-trace-datong-{uuid.uuid4()}",
        )
        body = await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message="我现在在大同喜晋道，不知道吃什么",
        )

        _assert_full_loop_trace(body)
        assert _ordered_tool_names(body) == ["search_knowledge", "create_recommendation_card"]
        assert "show_recommendation_card" in _ui_event_types(body)
        prompt_versions = _prompt_versions(body)
        assert prompt_versions["reasoner.system"]["version"] >= 1
        assert "content" not in prompt_versions["reasoner.system"]

    run_async(scenario)


def test_chat_turn_persists_full_loop_trace_for_help_draft(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        boot = await bootstrap(
            async_client,
            device_id=f"pytest-product-trace-help-{uuid.uuid4()}",
        )
        body = await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message="韩国逛街，不去明洞，想小众",
        )

        _assert_full_loop_trace(body)
        assert _ordered_tool_names(body) == ["search_knowledge", "draft_help_card"]
        assert "show_help_card_draft" in _ui_event_types(body)

    run_async(scenario)


def test_greeting_persists_turn_but_no_tool_trace(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        boot = await bootstrap(
            async_client,
            device_id=f"pytest-product-trace-greeting-{uuid.uuid4()}",
        )
        body = await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message="你好",
        )

        assert body["ui_events"] == []
        assert _ordered_tool_names(body) == []

        counts = _conversation_runtime_counts(body["conversation_id"])
        assert counts["turns"] >= 2
        assert counts["questions"] == 0
        assert counts["tool_calls"] == 0
        assert counts["retrieval_runs"] == 0

        trace = _loop_trace_for_response(body)
        assert "tool_call" not in _event_names(trace)
        assert "tool_result" not in _event_names(trace)

    run_async(scenario)
