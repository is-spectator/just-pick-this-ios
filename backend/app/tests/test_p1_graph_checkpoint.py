from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from langgraph.checkpoint.memory import MemorySaver

import app.agent.pipi_chat_graph as pipi_chat_graph
import app.services.chat as chat_service
from app.agent.model_adapter import get_deterministic_model_adapter

from .conftest import bootstrap, chat_turn


class _CapturingGraph:
    def __init__(self) -> None:
        self.invoke_calls: list[dict[str, Any]] = []

    def invoke(self, state: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        self.invoke_calls.append({"state": state, "config": config})
        return {
            **state,
            "intent": "greeting",
            "next_action": "respond",
            "assistant_message": "checkpoint capture graph response",
        }


def test_pipi_graph_uses_conversation_thread_id(
    run_async: Any,
    async_client: AsyncClient,
    monkeypatch: Any,
) -> None:
    async def scenario() -> None:
        graph = _CapturingGraph()
        monkeypatch.setattr(chat_service, "build_pipi_chat_graph", lambda: graph)

        boot = await bootstrap(
            async_client,
            device_id=f"pytest-graph-thread-id-{uuid.uuid4()}",
        )
        await chat_turn(
            async_client,
            conversation_id=boot["conversation_id"],
            message="你好",
        )

        assert len(graph.invoke_calls) == 1
        invoke_config = graph.invoke_calls[0]["config"]
        assert invoke_config == {
            "configurable": {
                "thread_id": boot["conversation_id"],
            }
        }

    run_async(scenario)


def test_graph_checkpoint_created_for_chat_turn(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        pipi_chat_graph,
        "get_pipi_model_adapter",
        get_deterministic_model_adapter,
    )

    checkpointer = MemorySaver()
    graph = pipi_chat_graph.build_pipi_chat_graph(checkpointer=checkpointer)
    thread_id = f"pytest-checkpoint-{uuid.uuid4()}"

    state = graph.invoke(
        {
            "conversation_id": thread_id,
            "user_turn_id": f"turn-{uuid.uuid4()}",
            "user_message": "你好",
            "agent_run_id": f"agent-run-{uuid.uuid4()}",
            "metadata": {},
        },
        {"configurable": {"thread_id": thread_id}},
    )

    checkpoint = checkpointer.get_tuple({"configurable": {"thread_id": thread_id}})
    assert state["assistant_message"]
    assert checkpoint is not None
    assert checkpoint.config["configurable"]["thread_id"] == thread_id
