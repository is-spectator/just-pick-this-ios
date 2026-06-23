from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import get_settings
from app.models import AgentRun
from app.services.runtime import session_scope

from .conftest import bootstrap, chat_turn


def _agent_output(agent_run_id: str) -> dict[str, Any]:
    with session_scope() as session:
        agent_run = session.get(AgentRun, uuid.UUID(agent_run_id))
        assert agent_run is not None
        return dict(agent_run.output_json or {})


def _latest_agent_output(conversation_id: str) -> dict[str, Any]:
    with session_scope() as session:
        agent_run = session.scalars(
            select(AgentRun)
            .where(AgentRun.conversation_id == uuid.UUID(conversation_id))
            .order_by(AgentRun.created_at.desc())
            .limit(1)
        ).first()
        assert agent_run is not None
        return dict(agent_run.output_json or {})


def test_llm_rewrite_mock_enters_product_loop_for_missing_known_area(
    run_async: Any,
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_REWRITE_ENABLED", "true")
    monkeypatch.setenv("LLM_PROVIDER", "mock_shadow")
    monkeypatch.setenv("LLM_MODEL", "mock-shadow-v0")
    monkeypatch.setenv("PIPI_EVAL_MODE", "false")
    monkeypatch.setenv("ALLOW_EVAL_BYPASS", "false")
    get_settings.cache_clear()

    async def scenario() -> None:
        boot = await bootstrap(
            async_client,
            device_id=f"pytest-llm-rewrite-product-{uuid.uuid4()}",
        )
        body = await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message="我在北京鼓楼，想吃川菜，你直接帮我选一个",
        )

        assert body["metadata"]["runtime_path"] == "product"
        assert body["response_kind"] in {"recommendation_card", "help_card_draft"}
        assert body["response_kind"] != "clarification"
        input_gate = body["metadata"]["input_gate"]
        assert input_gate["route_priority"] == "area_food"
        assert input_gate["location_state"] == "in_area"
        assert input_gate["extracted_slots"]["area"] == "鼓楼"
        assert body["metadata"]["query_rewrite_selection"]["accepted"] is True
        assert body["metadata"]["llm_query_rewrite"]["status"] == "success"

        output = _agent_output(body["metadata"]["agent_run_id"])
        events = [event.get("event") for event in output.get("loop_trace", [])]
        assert "query_rewrite_result" in events
        assert output["metadata"]["query_rewrite_selection"]["accepted"] is True

    try:
        run_async(scenario)
    finally:
        get_settings.cache_clear()


def test_llm_rewrite_low_confidence_does_not_change_product_route(
    run_async: Any,
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_REWRITE_ENABLED", "true")
    monkeypatch.setenv("LLM_PROVIDER", "mock_shadow")
    get_settings.cache_clear()

    async def scenario() -> None:
        boot = await bootstrap(
            async_client,
            device_id=f"pytest-llm-rewrite-low-confidence-{uuid.uuid4()}",
        )
        body = await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message="我在北京低置信鼓楼，想吃川菜，你直接帮我选一个",
        )

        assert body["response_kind"] == "clarification"
        assert body["metadata"]["query_rewrite_selection"]["accepted"] is False
        assert body["metadata"]["llm_query_rewrite"]["status"] == "low_confidence"
        output = _latest_agent_output(body["conversation_id"])
        assert output["metadata"]["query_rewrite_selection"]["accepted"] is False

    try:
        run_async(scenario)
    finally:
        get_settings.cache_clear()
