from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.agent import pipi_chat_graph
from app.config import get_settings


class CaptureGraph:
    def __init__(self) -> None:
        self.config: dict[str, Any] | None = None

    async def ainvoke(self, state: dict[str, Any], config: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        self.config = config
        return dict(state)


def test_thread_id_uses_conversation_id() -> None:
    conversation_id = str(uuid.uuid4())
    runner = pipi_chat_graph._PipiChatGraphRunner(CaptureGraph(), checkpoint_mode="fallback")
    config = runner._thread_config({"conversation_id": conversation_id}, None)
    assert config["configurable"]["thread_id"] == conversation_id


def test_checkpoint_required_but_disabled_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT_REQUIRED", "true")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT_BACKEND", "disabled")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="backend is disabled"):
        pipi_chat_graph.build_pipi_chat_graph()
    get_settings.cache_clear()


def test_dev_memory_checkpoint_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT_REQUIRED", "false")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT_BACKEND", "memory")
    get_settings.cache_clear()
    graph = pipi_chat_graph.build_pipi_chat_graph()
    assert graph._checkpoint_mode in {"langgraph", "fallback"}
    get_settings.cache_clear()
