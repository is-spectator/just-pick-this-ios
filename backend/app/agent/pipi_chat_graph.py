"""LangGraph V0 outer orchestration for deterministic Pipi chat turns."""

from __future__ import annotations

import asyncio
import inspect
from importlib import import_module
import uuid
from typing import Any

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from app.config import get_settings
from app.agent.model_adapter import get_pipi_model_adapter
from app.agent.pipi_loop import PipiLoop, PipiState
from app.agent.state import (
    ContextSnapshot,
    EvidenceEvaluation,
    KnowledgeRetriever,
    PipiChatGraphState,
    QueryRewrite,
    RetrievalHit,
    RetrievalRun,
    ToolExecutionResult,
    ToolExecutor,
)
from app.harness.evidence_evaluator import evaluate_retrieval_hits
from app.harness.input_gate import InputGateResult, direct_answer_for_gate, run_input_gate
from app.services.query_rewrite import QueryRewriteResult


def persist_turn(state: PipiChatGraphState) -> PipiChatGraphState:
    """Accept an already-persisted user turn and start an agent run placeholder."""

    metadata = {**state.get("metadata", {})}
    metadata.setdefault("persist_turn", {"status": "already_persisted"})

    return {
        **state,
        "agent_run_id": state.get("agent_run_id", f"agent-run:{state['user_turn_id']}"),
        "metadata": metadata,
    }


# Backward-compatible export for callers that still import the old node name.
ingest_turn = persist_turn


def input_gate(state: PipiChatGraphState) -> PipiChatGraphState:
    """Apply the harness gate before context, retrieval, or tool selection."""

    metadata = {**state.get("metadata", {})}
    active_help_card_id = metadata.get("help_card_id") or metadata.get("active_help_card_id")
    latest_user_context = metadata.get("latest_user_context")
    rewrite_override = _query_rewrite_override(metadata)
    gate = run_input_gate(
        state["user_message"],
        active_help_card_id=str(active_help_card_id) if active_help_card_id else None,
        latest_user_context=str(latest_user_context) if latest_user_context else None,
        client_context=dict(metadata.get("client_context") or {}),
        rewrite_result=rewrite_override,
    )
    gate_payload = gate.model_dump()
    metadata["input_gate_result"] = gate_payload
    metadata["allowed_tools"] = list(gate.allowed_tools)
    updated: PipiChatGraphState = {
        **state,
        "intent": gate.intent_type,
        "query_rewrite": _query_rewrite_from_gate(state, gate_payload),
        "metadata": metadata,
    }
    updated = _append_loop_trace(updated, "input_gate_result", gate_payload)
    if isinstance(metadata.get("llm_query_rewrite"), dict):
        updated = _append_loop_trace(
            updated,
            "query_rewrite_result",
            {
                "deterministic_or_selected": gate_payload,
                "llm_query_rewrite": metadata["llm_query_rewrite"],
                "query_rewrite_selection": metadata.get("query_rewrite_selection"),
            },
        )
    return updated


def direct_answer_or_build_context(state: PipiChatGraphState) -> PipiChatGraphState:
    """Either answer a gated turn directly or assemble the loop context pack."""

    metadata = {**state.get("metadata", {})}
    gate = dict(metadata.get("input_gate_result") or {})
    latest_user_context = metadata.get("latest_user_context")

    if gate.get("should_enter_loop") is False and not _should_force_llm_direct_answer_loop():
        assistant_message = state.get("assistant_message")
        if not assistant_message:
            assistant_message = direct_answer_for_gate(
                InputGateResult.model_validate(gate),
                state["user_message"],
                latest_user_context=str(latest_user_context) if latest_user_context else None,
            )
        metadata["context_mode"] = "direct_answer"
        updated: PipiChatGraphState = {
            **state,
            "assistant_message": assistant_message,
            "metadata": metadata,
        }
        return _append_loop_trace(
            updated,
            "direct_answer",
            {"message": assistant_message, "reason": gate.get("reason", "")},
        )

    current = build_context({**state, "metadata": metadata})

    current_metadata = {**current.get("metadata", {})}
    current_metadata["context_mode"] = "loop_context"
    current_metadata["context_pack"] = _context_pack_for_loop(current)
    return _append_loop_trace(
        {**current, "metadata": current_metadata},
        "context_pack",
        current_metadata["context_pack"],
    )


async def run_pipi_loop(state: PipiChatGraphState) -> PipiChatGraphState:
    """Run the inner Pipi loop as one LangGraph node."""

    if state.get("assistant_message"):
        return _finish_loop_response(
            state,
            iterations=0,
            finish_reason="direct_answer",
            tool_calls=[],
        )

    metadata = {**state.get("metadata", {})}
    runner = metadata.get("pipi_loop_runner")
    if callable(runner):
        result = runner(state)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, dict):
            return _merge_loop_runner_state(state, result)

    # Fallback for direct graph tests or development calls without the service
    # DB-backed AbilityCenter. This still runs the Harness PipiLoop; it does not
    # use the legacy retrieve/decide/execute graph branch.
    gate = dict(metadata.get("input_gate_result") or {})
    allowed_tools = list(metadata.get("allowed_tools") or gate.get("allowed_tools") or [])
    loop_result = await PipiLoop(max_iters=2).run(
        PipiState(
            conversation_id=state["conversation_id"],
            turn_id=state["user_turn_id"],
            user_message=state["user_message"],
            intent=state.get("intent") or gate.get("intent_type") or "unknown",
            intent_type=state.get("intent") or gate.get("intent_type") or "unknown",
            allowed_tools=allowed_tools,
            context_pack=dict(metadata.get("context_pack") or state.get("context_pack") or {}),
            metadata=_serializable_metadata(metadata),
        )
    )
    return _merge_loop_runner_state(
        state,
        {
            "assistant_message": loop_result.message,
            "loop_result_state": loop_result.state,
            "loop_trace": loop_result.trace,
            "loop_iterations": loop_result.iterations,
            "loop_finish_reason": loop_result.finish_reason,
        },
    )


def persist_response(state: PipiChatGraphState) -> PipiChatGraphState:
    """Mark response persistence for the service boundary."""

    updated = state
    if not updated.get("assistant_message"):
        adapter = get_pipi_model_adapter()
        updated = {**updated, "assistant_message": adapter.compose_response(updated)}

    metadata = {**updated.get("metadata", {})}
    metadata.setdefault("persist_response", {"status": "deferred_to_chat_service"})
    return {**updated, "metadata": metadata}


def classify_intent(state: PipiChatGraphState) -> PipiChatGraphState:
    """Classify the user turn before retrieval or tool selection."""

    adapter = get_pipi_model_adapter()
    classify_with_context = getattr(adapter, "classify_intent_for_state", None)
    if callable(classify_with_context):
        intent = classify_with_context(state)
    else:
        intent = adapter.classify_intent(state["user_message"])
    return {**state, "intent": intent}


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


# ---------------------------------------------------------------------------
# Deprecated legacy business nodes
#
# These functions are kept as module-level compatibility aliases for older
# tests/tools that imported them directly. They are not part of the compiled
# PipiChatGraph path; the product graph is now only the thin wrapper around
# InputGate -> ContextBuilder -> PipiLoop -> persist_response.
# ---------------------------------------------------------------------------


def _deprecated_rewrite_query(state: PipiChatGraphState) -> PipiChatGraphState:
    """Deprecated legacy node: query rewrite now belongs inside the loop context."""

    adapter = get_pipi_model_adapter()
    rewrite_with_context = getattr(adapter, "rewrite_query_for_state", None)
    if callable(rewrite_with_context):
        rewrite = rewrite_with_context(state)
    else:
        query = _query_for_state(state)
        rewrite = {
            "original": query,
            "rewritten": query,
            "changed": False,
            "method": "identity",
            "reason": "Adapter has no query rewrite implementation.",
            "entities": {},
        }

    context = dict(state.get("context") or {})
    facts = dict(context.get("facts") or {})
    rewritten = str(rewrite.get("rewritten") or "").strip()
    if rewritten:
        facts["rewritten_query"] = rewritten
        facts["query_rewrite_changed"] = bool(rewrite.get("changed"))
    context["facts"] = facts
    return {**state, "query_rewrite": rewrite, "context": context}


def _deprecated_retrieve_knowledge(state: PipiChatGraphState) -> PipiChatGraphState:
    """Deprecated legacy node: retrieval now runs through AbilityCenter tools."""

    if state.get("intent") not in {"decision_request", "help_request"}:
        return {
            **state,
            "retrieval_run": {
                "id": "",
                "query": _query_for_state(state),
                "hits": [],
                "metadata": {"status": "skipped_non_decision_intent"},
            },
            "retrieval_hits": [],
        }

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


def _deprecated_evaluate_evidence(state: PipiChatGraphState) -> PipiChatGraphState:
    """Deprecated legacy node: evidence evaluation now runs inside PipiLoop."""

    return {**state, "evidence_evaluation": _evaluate_retrieval_hits(state.get("retrieval_hits", []))}


def _deprecated_decide_next_action(state: PipiChatGraphState) -> PipiChatGraphState:
    """Deprecated legacy node: Reasoner decisions now happen inside PipiLoop."""

    adapter = get_pipi_model_adapter()
    next_action, tool_call = adapter.decide_next_action(state)
    updated: PipiChatGraphState = {**state, "next_action": next_action}
    if tool_call is not None:
        updated["tool_call"] = tool_call
    return _append_loop_trace(
        updated,
        "reasoner_decision",
        {
            "type": "tool" if tool_call is not None else "answer",
            "next_action": next_action,
            "tool_call": tool_call,
        },
    )


def _deprecated_execute_tool(state: PipiChatGraphState) -> PipiChatGraphState:
    """Deprecated legacy node: tools now execute through AbilityCenter."""

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

    return _append_loop_trace({**state, "tool_execution": result}, "tool_result", result)


def _execute_loop_tool(tool_call: dict[str, Any], state: PipiChatGraphState) -> ToolExecutionResult:
    executor = state.get("metadata", {}).get("tool_executor")
    if tool_call.get("name") == "finalize_help_card":
        return _run_finalize_graph_tool(tool_call, state, executor)

    if executor is None:
        executor = _load_optional_factory("app.tools.registry", "get_tool_executor")

    if isinstance(executor, ToolExecutor):
        try:
            return executor.execute(tool_call, state)
        except Exception as exc:  # pragma: no cover - defensive boundary for future services
            return {
                "status": "failed",
                "name": str(tool_call.get("name") or ""),
                "error": str(exc),
            }

    return {
        "status": "unavailable",
        "name": str(tool_call.get("name") or ""),
        "result": {"tool_call": dict(tool_call)},
    }


def _run_finalize_graph_tool(
    tool_call: dict[str, Any],
    state: PipiChatGraphState,
    executor: Any,
) -> ToolExecutionResult:
    arguments = dict(tool_call.get("arguments") or {})
    metadata = dict(state.get("metadata") or {})
    help_card_id = arguments.get("help_card_id") or metadata.get("help_card_id") or metadata.get(
        "active_help_card_id"
    )
    session = getattr(executor, "session", None)
    if session is None or not help_card_id:
        return {
            "status": "unavailable",
            "name": "finalize_help_card",
            "result": {
                "deferred": True,
                "reason": "finalize_graph_requires_persisted_help_card",
            },
        }

    try:
        runner = _load_optional_function(
            "app.jobs.finalizer_job",
            "run_finalize_graph_for_help_card",
        )
        if runner is None:
            return {
                "status": "unavailable",
                "name": "finalize_help_card",
                "result": {"deferred": True, "reason": "finalize_graph_unavailable"},
            }

        final_state = runner(session, help_card_id)
        _hydrate_finalized_outputs(executor, final_state)
        finalize_status = str(final_state.get("status") or "")
        if finalize_status == "failed":
            return {
                "status": "failed",
                "name": "finalize_help_card",
                "result": {"finalize_graph_state": _finalize_graph_summary(final_state)},
            }
        if finalize_status == "needs_more_answers":
            return {
                "status": "skipped",
                "name": "finalize_help_card",
                "result": {"finalize_graph_state": _finalize_graph_summary(final_state)},
            }
        return {
            "status": "succeeded",
            "name": "finalize_help_card",
            "result": {"finalize_graph_state": _finalize_graph_summary(final_state)},
        }
    except Exception as exc:  # pragma: no cover - defensive boundary for DB-backed finalization
        return {
            "status": "failed",
            "name": "finalize_help_card",
            "error": str(exc),
        }


def _hydrate_finalized_outputs(executor: Any, final_state: dict[str, Any]) -> None:
    session = getattr(executor, "session", None)
    if session is None:
        return

    card_payload = dict(final_state.get("final_recommendation_card") or {})
    card_id = card_payload.get("id") or card_payload.get("card_id")
    help_card_id = final_state.get("help_card_id")
    if card_id:
        try:
            from app.models import HelpCard, LightEvent, RecommendationCard
            from app.services.runtime import build_card_ui_event

            card = session.get(RecommendationCard, uuid.UUID(str(card_id)))
            if card is not None and hasattr(executor, "cards"):
                executor.cards.append(card)
                if hasattr(executor, "ui_events"):
                    executor.ui_events.append(build_card_ui_event(card))

            if help_card_id and hasattr(executor, "help_cards"):
                help_card = session.get(HelpCard, uuid.UUID(str(help_card_id)))
                if help_card is not None:
                    executor.help_cards.append(help_card)

            if help_card_id and hasattr(executor, "light_events"):
                events = list(
                    session.scalars(
                        select(LightEvent)
                        .where(LightEvent.help_card_id == uuid.UUID(str(help_card_id)))
                        .order_by(LightEvent.created_at.desc())
                        .limit(1)
                    )
                )
                executor.light_events.extend(events)
        except Exception:
            return


def _finalize_graph_summary(final_state: dict[str, Any]) -> dict[str, Any]:
    card = dict(final_state.get("final_recommendation_card") or {})
    light = dict(final_state.get("light_event") or {})
    intent_answer = dict(final_state.get("intent_answer") or {})
    return {
        "status": final_state.get("status"),
        "help_card_id": final_state.get("help_card_id"),
        "recommendation_card_id": card.get("id") or card.get("card_id"),
        "intent_answer_id": intent_answer.get("id"),
        "light_event_id": light.get("id"),
    }


def _deprecated_respond(state: PipiChatGraphState) -> PipiChatGraphState:
    """Deprecated legacy node: final answers now come from PipiLoop/AnswerGate."""

    if state.get("assistant_message"):
        return _append_loop_trace(
            state,
            "answer",
            {"message": state.get("assistant_message"), "ui_events": []},
        )
    adapter = get_pipi_model_adapter()
    updated: PipiChatGraphState = {**state, "assistant_message": adapter.compose_response(state)}
    return _append_loop_trace(
        updated,
        "answer",
        {"message": updated.get("assistant_message"), "ui_events": []},
    )


# Backward-compatible names for direct module imports only. Do not export these
# from app.agent, and do not add them to build_pipi_chat_graph().
rewrite_query = _deprecated_rewrite_query
retrieve_knowledge = _deprecated_retrieve_knowledge
evaluate_evidence = _deprecated_evaluate_evidence
decide_next_action = _deprecated_decide_next_action
execute_tool = _deprecated_execute_tool
respond = _deprecated_respond


def build_pipi_chat_graph(checkpointer: Any | None = None) -> Any:
    """Compile the thin PipiChatGraph wrapper around the PipiLoop engine."""

    checkpointer = _resolve_checkpointer(checkpointer)
    graph = StateGraph(PipiChatGraphState)

    graph.add_node("persist_turn", persist_turn)
    graph.add_node("input_gate", input_gate)
    graph.add_node("build_context", direct_answer_or_build_context)
    graph.add_node("run_pipi_loop", run_pipi_loop)
    graph.add_node("persist_response", persist_response)

    graph.add_edge(START, "persist_turn")
    graph.add_edge("persist_turn", "input_gate")
    graph.add_edge("input_gate", "build_context")
    graph.add_edge("build_context", "run_pipi_loop")
    graph.add_edge("run_pipi_loop", "persist_response")
    graph.add_edge("persist_response", END)

    compiled, checkpoint_mode = _compile_chat_graph(graph, checkpointer)
    return _PipiChatGraphRunner(compiled, checkpoint_mode=checkpoint_mode)


class _PipiChatGraphRunner:
    """Small invoke adapter that pins LangGraph checkpoints to conversation id."""

    def __init__(self, compiled_graph: Any, *, checkpoint_mode: str) -> None:
        self._compiled_graph = compiled_graph
        self._checkpoint_mode = checkpoint_mode

    def invoke(
        self,
        input: PipiChatGraphState,
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> PipiChatGraphState:
        return asyncio.run(self.ainvoke(input, config, **kwargs))

    async def ainvoke(
        self,
        input: PipiChatGraphState,
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> PipiChatGraphState:
        state = self._prepare_state(input)
        if self._checkpoint_mode == "fallback" and not _has_running_asyncio_loop():
            return await self._ainvoke_fallback_path(state)
        return await self._compiled_graph.ainvoke(
            state,
            self._thread_config(state, config),
            **kwargs,
        )

    def stream(
        self,
        input: PipiChatGraphState,
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        state = self._prepare_state(input)
        return self._compiled_graph.stream(
            state,
            self._thread_config(state, config),
            **kwargs,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._compiled_graph, name)

    @staticmethod
    async def _ainvoke_fallback_path(state: PipiChatGraphState) -> PipiChatGraphState:
        current = persist_turn(state)
        current = input_gate(current)
        current = direct_answer_or_build_context(current)
        current = await run_pipi_loop(current)
        return persist_response(current)

    def _prepare_state(self, state: PipiChatGraphState) -> PipiChatGraphState:
        metadata = {**state.get("metadata", {})}
        if self._checkpoint_mode == "fallback":
            metadata["checkpoint_mode"] = "fallback"
        else:
            metadata.setdefault("checkpoint_mode", self._checkpoint_mode)
        return {**state, "metadata": metadata}

    @staticmethod
    def _thread_config(
        state: PipiChatGraphState,
        config: dict[str, Any] | None,
    ) -> dict[str, Any]:
        merged = {**(config or {})}
        configurable = {**(merged.get("configurable") or {})}
        configurable["thread_id"] = str(state["conversation_id"])
        merged["configurable"] = configurable
        return merged


def _should_force_llm_direct_answer_loop() -> bool:
    settings = get_settings()
    return settings.pipi_model_provider == "openai" and settings.openai_api_key is not None


def _compile_chat_graph(
    graph: StateGraph,
    checkpointer: Any | None,
) -> tuple[Any, str]:
    if not _checkpointer_available(checkpointer):
        settings = get_settings()
        if settings.langgraph_checkpoint_required:
            raise RuntimeError("LangGraph checkpoint is required but no checkpointer is available")
        return graph.compile(), "fallback"
    try:
        return graph.compile(checkpointer=checkpointer), "langgraph"
    except Exception:
        if get_settings().langgraph_checkpoint_required:
            raise
        return graph.compile(), "fallback"


def _resolve_checkpointer(checkpointer: Any | None) -> Any | None:
    if checkpointer is not None:
        return checkpointer
    settings = get_settings()
    if settings.langgraph_checkpoint_backend == "disabled":
        if settings.langgraph_checkpoint_required:
            raise RuntimeError("LangGraph checkpoint is required but backend is disabled")
        return None
    if settings.langgraph_checkpoint_backend == "memory":
        try:
            from langgraph.checkpoint.memory import MemorySaver

            return MemorySaver()
        except Exception:
            if settings.langgraph_checkpoint_required:
                raise
            return None
    if settings.langgraph_checkpoint_backend == "postgres":
        if settings.langgraph_checkpoint_required:
            raise RuntimeError("Postgres LangGraph checkpointer is not configured")
        return None
    return None


def _checkpointer_available(checkpointer: Any | None) -> bool:
    if checkpointer is None:
        return False
    sync_available = all(
        hasattr(checkpointer, method_name) for method_name in ("get_tuple", "put", "put_writes")
    )
    async_available = all(
        hasattr(checkpointer, method_name) for method_name in ("aget_tuple", "aput", "aput_writes")
    )
    return sync_available or async_available


def _has_running_asyncio_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


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
        "query": _query_for_state(state),
        "hits": [],
        "metadata": {"status": "retriever_unavailable"},
    }


def _query_for_state(state: PipiChatGraphState) -> str:
    rewrite: QueryRewrite = state.get("query_rewrite", {})
    rewritten = str(rewrite.get("rewritten") or "").strip()
    if rewritten:
        return rewritten
    facts = dict((state.get("context") or {}).get("facts") or {})
    resolved = str(facts.get("resolved_user_message") or "").strip()
    return resolved or state["user_message"].strip()


def _query_rewrite_override(metadata: dict[str, Any]) -> QueryRewriteResult | None:
    payload = metadata.get("query_rewrite_override")
    if not isinstance(payload, dict):
        return None
    try:
        return QueryRewriteResult.model_validate(payload)
    except Exception:
        return None


def _query_rewrite_from_gate(
    state: PipiChatGraphState,
    gate_payload: dict[str, Any],
) -> QueryRewrite:
    canonical = str(gate_payload.get("canonical_query") or state.get("user_message") or "")
    original = str(state.get("user_message") or "")
    return {
        "original": original,
        "rewritten": canonical,
        "changed": bool(canonical and canonical != original),
        # Keep the product enrichment step enabled. DbPipiAbilityCenter treats this
        # method as the lightweight InputGate rewrite and merges it with the richer
        # deterministic adapter rewrite before retrieval/tool execution.
        "method": "deterministic_input_gate",
        "reason": str(gate_payload.get("reason") or ""),
        "entities": dict(gate_payload.get("extracted_slots") or {}),
    }


def _evaluate_retrieval_hits(hits: list[RetrievalHit]) -> EvidenceEvaluation:
    return evaluate_retrieval_hits(hits)  # type: ignore[return-value]


def _context_pack_for_loop(state: PipiChatGraphState) -> dict[str, Any]:
    hits = list(state.get("retrieval_hits", []))
    strongest_evidence = sorted(
        hits,
        key=lambda hit: float(hit.get("score") or 0.0),
        reverse=True,
    )
    metadata = dict(state.get("metadata") or {})
    gate = metadata.get("input_gate_result") if isinstance(metadata.get("input_gate_result"), dict) else {}
    query_rewrite = state.get("query_rewrite", {})
    if not query_rewrite and isinstance(gate, dict):
        query_rewrite = {
            "original": state.get("user_message"),
            "rewritten": gate.get("canonical_query") or state.get("user_message"),
            "changed": bool(gate.get("canonical_query") and gate.get("canonical_query") != state.get("user_message")),
            "method": "deterministic_input_gate",
            "reason": gate.get("reason"),
            "entities": gate.get("extracted_slots") or {},
        }
    return {
        "conversation_id": state["conversation_id"],
        "turn_id": state["user_turn_id"],
        "context": state.get("context", {}),
        "query_rewrite": query_rewrite,
        "retrieval_run": state.get("retrieval_run", {}),
        "retrieval_hits": hits,
        "strongest_evidence": strongest_evidence,
        "evidence_evaluation": state.get("evidence_evaluation", {}),
    }


def _finish_loop_response(
    state: PipiChatGraphState,
    *,
    iterations: int,
    finish_reason: str,
    tool_calls: list[str],
) -> PipiChatGraphState:
    metadata = {**state.get("metadata", {})}
    metadata["pipi_loop_result"] = {
        "iterations": iterations,
        "finish_reason": finish_reason,
        "tool_calls": tool_calls,
    }
    return _append_loop_trace(
        {**state, "metadata": metadata},
        "answer",
        {
            "message": state.get("assistant_message"),
            "ui_events": [],
            "finish_reason": finish_reason,
        },
    )


def _merge_loop_runner_state(
    state: PipiChatGraphState,
    loop_payload: dict[str, Any],
) -> PipiChatGraphState:
    loop_state = dict(loop_payload.get("loop_result_state") or loop_payload.get("state") or {})
    loop_metadata = dict(loop_state.get("metadata") or {})
    metadata = {
        **_serializable_metadata(state.get("metadata", {})),
        **_serializable_metadata(loop_metadata),
    }
    metadata["pipi_loop_result"] = {
        "iterations": loop_payload.get("loop_iterations") or loop_payload.get("iterations") or 0,
        "finish_reason": loop_payload.get("loop_finish_reason")
        or loop_payload.get("finish_reason")
        or "answer",
        "tool_calls": _tool_names_from_trace(loop_payload.get("loop_trace") or []),
    }

    updated: PipiChatGraphState = {
        **state,
        "assistant_message": str(loop_payload.get("assistant_message") or loop_payload.get("message") or ""),
        "metadata": metadata,
        "context_pack": dict(loop_state.get("context_pack") or state.get("context_pack") or {}),
    }
    if loop_state.get("intent"):
        updated["intent"] = loop_state["intent"]
    trace = list(loop_payload.get("loop_trace") or [])
    if trace:
        updated["loop_trace"] = trace  # type: ignore[typeddict-unknown-key]
    return _finish_loop_response(
        updated,
        iterations=int(metadata["pipi_loop_result"]["iterations"] or 0),
        finish_reason=str(metadata["pipi_loop_result"]["finish_reason"] or "answer"),
        tool_calls=list(metadata["pipi_loop_result"]["tool_calls"] or []),
    )


def _tool_names_from_trace(trace: Any) -> list[str]:
    names: list[str] = []
    if not isinstance(trace, list):
        return names
    for event in trace:
        if not isinstance(event, dict) or event.get("event") != "reasoner_decision":
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if data.get("tool_name"):
            names.append(str(data["tool_name"]))
            continue
        tool_call = data.get("tool_call")
        if isinstance(tool_call, dict) and (tool_call.get("name") or tool_call.get("tool_name")):
            names.append(str(tool_call.get("name") or tool_call.get("tool_name")))
    return names


def _serializable_metadata(metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    return {
        key: value
        for key, value in metadata.items()
        if isinstance(value, (str, int, float, bool, type(None), list, dict))
    }


def _append_loop_trace(
    state: PipiChatGraphState,
    event: str,
    data: dict[str, Any],
) -> PipiChatGraphState:
    trace = list(state.get("loop_trace", []))  # type: ignore[typeddict-item]
    trace.append({"event": event, "data": data})
    return {**state, "loop_trace": trace}  # type: ignore[typeddict-unknown-key]


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


def _load_optional_function(module_name: str, function_name: str) -> Any | None:
    try:
        module = import_module(module_name)
    except ImportError:
        return None
    function = getattr(module, function_name, None)
    return function if callable(function) else None
