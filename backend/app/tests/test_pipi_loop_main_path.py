from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient

import app.agent.pipi_chat_graph as pipi_chat_graph
from app.agent.pipi_loop import PipiLoop
from app.agent.schemas import PipiLoopResult

from .conftest import bootstrap, chat_turn


def _graph_node_names() -> set[str]:
    graph = pipi_chat_graph.build_pipi_chat_graph()
    compiled = getattr(graph, "_compiled_graph", graph)
    return set(getattr(compiled, "nodes", {}).keys())


def _ordered_tool_names(body: dict[str, Any]) -> list[str]:
    return [
        str(tool.get("name") or tool.get("tool_name"))
        for tool in body.get("tool_calls", [])
        if tool.get("name") or tool.get("tool_name")
    ]


def test_chat_turn_invokes_pipi_loop(
    run_async: Any,
    async_client: AsyncClient,
    monkeypatch: Any,
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_run(self: PipiLoop, state: Any) -> PipiLoopResult:
        calls.append(state.model_dump(mode="json"))
        return PipiLoopResult(
            message="loop spy response",
            iterations=1,
            finish_reason="answer",
            trace=[
                {
                    "iteration": 1,
                    "event": "reasoner_decision",
                    "data": {"type": "answer", "message": "loop spy response"},
                },
                {
                    "iteration": 1,
                    "event": "answer_gate_result",
                    "data": {"passed": True},
                },
            ],
            state=state.model_dump(mode="json"),
        )

    monkeypatch.setattr(PipiLoop, "run", fake_run)

    async def scenario() -> None:
        boot = await bootstrap(
            async_client,
            device_id=f"pytest-pipi-loop-spy-{uuid.uuid4()}",
        )
        body = await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message="我现在在大同喜晋道，不知道吃什么，给我推荐一个。",
        )

        assert len(calls) == 1
        assert calls[0]["user_message"] == "我现在在大同喜晋道，不知道吃什么，给我推荐一个。"
        assert body["assistant_message"] == "loop spy response"
        assert body["metadata"]["loop"]["iterations"] > 0

    run_async(scenario)


def test_pipi_chat_graph_main_path_has_no_legacy_execute_nodes() -> None:
    nodes = _graph_node_names()

    assert {
        "persist_turn",
        "input_gate",
        "build_context",
        "run_pipi_loop",
        "persist_response",
    }.issubset(nodes)
    assert {
        "retrieve_knowledge",
        "decide_next_action",
        "execute_tool",
        "respond",
        "evaluate_evidence",
        "direct_answer_or_build_context",
    }.isdisjoint(nodes)


def test_datong_main_path_tool_sequence_and_loop_metadata(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        boot = await bootstrap(
            async_client,
            device_id=f"pytest-pipi-loop-datong-{uuid.uuid4()}",
        )
        body = await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message="我现在在大同喜晋道，不知道吃什么，给我推荐一个。",
        )

        assert _ordered_tool_names(body) == [
            "search_knowledge",
            "create_recommendation_card",
        ]
        assert body["metadata"]["loop"]["iterations"] > 0
        assert body["cards"]

    run_async(scenario)


def test_korea_main_path_tool_sequence_and_loop_metadata(
    run_async: Any,
    async_client: AsyncClient,
) -> None:
    async def scenario() -> None:
        boot = await bootstrap(
            async_client,
            device_id=f"pytest-pipi-loop-korea-{uuid.uuid4()}",
        )
        body = await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message="在韩国逛街，不想去明洞，想小众，求一个。",
        )

        assert _ordered_tool_names(body) == [
            "search_knowledge",
            "draft_help_card",
        ]
        assert body["metadata"]["loop"]["iterations"] > 0
        assert body["cards"] == []
        assert body["help_cards"]

    run_async(scenario)
