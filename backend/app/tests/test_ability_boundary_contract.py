from __future__ import annotations

import inspect
import json
import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

import app.agent.pipi_chat_graph as pipi_chat_graph
from app.agent.reasoner import DeterministicReasoner
from app.api import routes_chat
from app.models import AgentRun, ToolCall
from app.services import chat as chat_service
from app.services.runtime import session_scope

from .conftest import bootstrap, chat_turn


def test_product_path_declares_db_pipi_ability_center_boundary() -> None:
    source = inspect.getsource(chat_service.run_chat_turn)

    assert "DbPipiAbilityCenter(" in source
    assert "ability_center=DbPipiAbilityCenter" in source
    assert "DbToolExecutor(" in source


def test_api_graph_and_reasoner_do_not_directly_call_db_tool_executor_on_main_path() -> None:
    api_source = inspect.getsource(routes_chat.chat_turn)
    graph_build_source = inspect.getsource(pipi_chat_graph.build_pipi_chat_graph)
    graph_loop_source = inspect.getsource(pipi_chat_graph.run_pipi_loop)
    reasoner_source = inspect.getsource(DeterministicReasoner.next)

    for source in (api_source, graph_build_source, graph_loop_source, reasoner_source):
        assert "DbToolExecutor" not in source
        assert ".execute(" not in source

    assert "pipi_loop_runner" in graph_loop_source


def test_chat_turn_tool_calls_are_persisted_by_product_ability_boundary(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        boot = await bootstrap(
            async_client,
            device_id=f"pytest-ability-boundary-datong-{uuid.uuid4()}",
        )
        body = await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message="我现在在大同喜晋道，不知道吃什么，给我推荐一个。",
        )

        assert body["metadata"]["agent_run_id"]
        assert body["metadata"]["loop"]["tool_calls"] == [
            "search_knowledge",
            "create_recommendation_card",
        ]

        agent_run_id = uuid.UUID(body["metadata"]["agent_run_id"])
        with session_scope() as session:
            agent_run = session.get(AgentRun, agent_run_id)
            assert agent_run is not None
            calls = list(
                session.scalars(
                    select(ToolCall)
                    .where(ToolCall.agent_run_id == agent_run_id)
                    .order_by(ToolCall.sequence_index)
                )
            )

            assert [call.tool_name for call in calls] == [
                "search_knowledge",
                "create_recommendation_card",
            ]
            assert all(call.status == "succeeded" for call in calls)

            trace = _loop_trace(agent_run)
            assert "DeferredAbilityCenter" not in json.dumps(
                {"metadata": body.get("metadata"), "trace": trace},
                ensure_ascii=False,
                default=str,
            )
            assert _tool_result_is_read_by_next_reasoner(trace)

    run_async(scenario)


def _loop_trace(agent_run: AgentRun) -> list[dict[str, Any]]:
    output = dict(agent_run.output_json or {})
    trace = output.get("loop_trace")
    assert isinstance(trace, list), output
    return [event for event in trace if isinstance(event, dict)]


def _tool_result_is_read_by_next_reasoner(trace: list[dict[str, Any]]) -> bool:
    for index, event in enumerate(trace):
        if event.get("event") != "tool_result":
            continue
        data = event.get("data") or {}
        if data.get("tool_name") != "search_knowledge":
            continue
        for later in trace[index + 1 :]:
            if later.get("event") != "reasoner_decision":
                continue
            later_data = later.get("data") or {}
            return later_data.get("tool_name") == "create_recommendation_card"
    return False
