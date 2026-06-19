"""Pipi agent runtime entry points.

This package intentionally avoids eager LangGraph imports. Leaf modules such as
``app.agent.model_adapter`` are used in lightweight unit tests and should not
load the graph stack until the product path actually builds a graph.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "ChatTurn",
    "ContextSnapshot",
    "DeterministicPipiModelAdapter",
    "OpenAIPipiModelAdapter",
    "PipiChatGraphState",
    "PipiLoop",
    "PipiState",
    "RetrievalHit",
    "RetrievalRun",
    "ToolCallDraft",
    "ToolExecutionResult",
    "build_context",
    "build_pipi_chat_graph",
    "build_pipi_loop",
    "get_deterministic_model_adapter",
    "get_pipi_model_adapter",
    "ingest_turn",
]


def __getattr__(name: str) -> Any:
    if name in {
        "DeterministicPipiModelAdapter",
        "OpenAIPipiModelAdapter",
        "get_deterministic_model_adapter",
        "get_pipi_model_adapter",
    }:
        from app.agent import model_adapter

        return getattr(model_adapter, name)
    if name in {"build_context", "build_pipi_chat_graph", "ingest_turn"}:
        from app.agent import pipi_chat_graph

        return getattr(pipi_chat_graph, name)
    if name in {"PipiLoop", "PipiState", "build_pipi_loop"}:
        from app.agent import pipi_loop

        return getattr(pipi_loop, name)
    if name in {
        "ChatTurn",
        "ContextSnapshot",
        "PipiChatGraphState",
        "RetrievalHit",
        "RetrievalRun",
        "ToolCallDraft",
        "ToolExecutionResult",
    }:
        from app.agent import state

        return getattr(state, name)
    raise AttributeError(name)
