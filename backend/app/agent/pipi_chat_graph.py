"""LangGraph V0 for deterministic Pipi chat turns."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent.model_adapter import get_deterministic_model_adapter
from app.agent.state import (
    ContextSnapshot,
    KnowledgeRetriever,
    PipiChatGraphState,
    RetrievalRun,
    ToolExecutionResult,
    ToolExecutor,
)


def ingest_turn(state: PipiChatGraphState) -> PipiChatGraphState:
    """Accept an already-persisted user turn and start an agent run placeholder."""

    metadata = {**state.get("metadata", {})}
    metadata.setdefault("ingest_turn", {"status": "already_persisted"})

    return {
        **state,
        "agent_run_id": state.get("agent_run_id", f"agent-run:{state['user_turn_id']}"),
        "metadata": metadata,
    }


def build_context(state: PipiChatGraphState) -> PipiChatGraphState:
    """Build conversation context through a future service when available."""

    provider = state.get("metadata", {}).get("context_provider")
    if provider is None:
        provider = _load_optional_factory("app.services.conversation_context", "get_context_provider")

    if provider is not None and hasattr(provider, "build_context"):
        context = provider.build_context(state)
    else:
        context = _default_context(state)

    return {**state, "context": context}


def retrieve_knowledge(state: PipiChatGraphState) -> PipiChatGraphState:
    """Retrieve knowledge before any tool decision, with a deterministic fallback."""

    retriever = state.get("metadata", {}).get("knowledge_retriever")
    if retriever is None:
        retriever = _load_optional_factory("app.retrieval.knowledge", "get_knowledge_retriever")

    if isinstance(retriever, KnowledgeRetriever):
        retrieval_run = retriever.retrieve(state)
    else:
        retrieval_run = _default_retrieval_run(state)

    return {
        **state,
        "retrieval_run": retrieval_run,
        "retrieval_hits": retrieval_run.get("hits", []),
    }


def decide_next_action(state: PipiChatGraphState) -> PipiChatGraphState:
    """Use the deterministic adapter to choose either respond or one tool call."""

    adapter = get_deterministic_model_adapter()
    next_action, tool_call = adapter.decide_next_action(state)
    updated: PipiChatGraphState = {**state, "next_action": next_action}
    if tool_call is not None:
        updated["tool_call"] = tool_call
    return updated


def execute_tool(state: PipiChatGraphState) -> PipiChatGraphState:
    """Execute at most one selected tool call through a future tool service."""

    tool_call = state.get("tool_call")
    if tool_call is None:
        return {**state, "tool_execution": {"status": "skipped", "name": ""}}

    executor = state.get("metadata", {}).get("tool_executor")
    if executor is None:
        executor = _load_optional_factory("app.tools.registry", "get_tool_executor")

    if isinstance(executor, ToolExecutor):
        try:
            result = executor.execute(tool_call, state)
        except Exception as exc:  # pragma: no cover - defensive boundary for future services
            result: ToolExecutionResult = {
                "status": "failed",
                "name": tool_call["name"],
                "error": str(exc),
            }
    else:
        result = {
            "status": "unavailable",
            "name": tool_call["name"],
            "result": {"tool_call": dict(tool_call)},
        }

    return {**state, "tool_execution": result}


def respond(state: PipiChatGraphState) -> PipiChatGraphState:
    """Compose the deterministic assistant response for this graph run."""

    adapter = get_deterministic_model_adapter()
    return {**state, "assistant_message": adapter.compose_response(state)}


def build_pipi_chat_graph() -> Any:
    """Compile PipiChatGraph V0.

    Node order:
    ingest_turn -> build_context -> retrieve_knowledge -> decide_next_action
    -> execute_tool (optional, once) -> respond.
    """

    graph = StateGraph(PipiChatGraphState)

    graph.add_node("ingest_turn", ingest_turn)
    graph.add_node("build_context", build_context)
    graph.add_node("retrieve_knowledge", retrieve_knowledge)
    graph.add_node("decide_next_action", decide_next_action)
    graph.add_node("execute_tool", execute_tool)
    graph.add_node("respond", respond)

    graph.add_edge(START, "ingest_turn")
    graph.add_edge("ingest_turn", "build_context")
    graph.add_edge("build_context", "retrieve_knowledge")
    graph.add_edge("retrieve_knowledge", "decide_next_action")
    graph.add_conditional_edges(
        "decide_next_action",
        _route_after_decision,
        {"execute_tool": "execute_tool", "respond": "respond"},
    )
    graph.add_edge("execute_tool", "respond")
    graph.add_edge("respond", END)

    return graph.compile()


def _route_after_decision(state: PipiChatGraphState) -> str:
    if state.get("next_action") == "call_tool":
        return "execute_tool"
    return "respond"


def _default_context(state: PipiChatGraphState) -> ContextSnapshot:
    return {
        "conversation_id": state["conversation_id"],
        "user_turn_id": state["user_turn_id"],
        "user_message": state["user_message"],
        "recent_turns": [
            {
                "id": state["user_turn_id"],
                "conversation_id": state["conversation_id"],
                "role": "user",
                "content": state["user_message"],
            }
        ],
        "facts": {},
    }


def _default_retrieval_run(state: PipiChatGraphState) -> RetrievalRun:
    return {
        "id": f"retrieval-run:{state['user_turn_id']}",
        "query": state["user_message"],
        "hits": [],
        "metadata": {"status": "retriever_unavailable"},
    }


def _load_optional_factory(module_name: str, factory_name: str) -> Any | None:
    try:
        module = import_module(module_name)
    except ImportError:
        return None

    factory = getattr(module, factory_name, None)
    if factory is None:
        return None
    try:
        return factory()
    except Exception:
        return None
