from __future__ import annotations

import asyncio
import inspect
from datetime import date, datetime
from time import perf_counter
from typing import Any, Protocol

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.agent.reasoner import DeterministicReasoner
from app.agent.schemas import AnswerDecision, PipiLoopResult, ReasonerDecision, ToolDecision, ToolResult
from app.agent.shadow_reasoner import ShadowReasonerResult
from app.config import get_settings


class PipiState(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True, str_strip_whitespace=True)

    conversation_id: str
    turn_id: str = Field(validation_alias=AliasChoices("turn_id", "user_turn_id"))
    user_message: str
    intent: str | None = None
    intent_type: str | None = None
    context_pack: dict[str, Any] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def append_tool_result(
        self,
        decision: ToolDecision,
        tool_result: ToolResult,
        eval_result: Any,
    ) -> "PipiState":
        next_context_pack = _context_pack_after_tool(self.context_pack, tool_result)
        return self.model_copy(
            update={
                "context_pack": next_context_pack,
                "tool_results": [
                    *self.tool_results,
                    {
                        "decision": decision.model_dump(),
                        "tool_result": tool_result.model_dump(),
                        "evaluation": _dump(eval_result),
                    },
                ]
            }
        )


class Reasoner(Protocol):
    async def next(self, state: PipiState) -> ReasonerDecision:
        """Return either a tool decision or final answer."""


class ShadowReasoner(Protocol):
    def run_shadow(
        self,
        context_pack: dict[str, Any],
        deterministic_decision: ReasonerDecision,
    ) -> Any:
        """Return an audit-only shadow result for a deterministic decision."""


class AbilityCenter(Protocol):
    async def call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        *,
        state: PipiState,
    ) -> ToolResult:
        """Execute a validated ability tool."""


class PipiLoop:
    def __init__(
        self,
        *,
        reasoner: Reasoner | None = None,
        ability_center: AbilityCenter | None = None,
        evaluator: Any | None = None,
        answer_gate: Any | None = None,
        trace_store: Any | None = None,
        shadow_reasoner: ShadowReasoner | None = None,
        shadow_enabled: bool | None = None,
        tool_timeout_seconds: float | None = None,
        max_iters: int = 6,
    ) -> None:
        self.reasoner = reasoner or DeterministicReasoner()
        self.ability_center = ability_center or DeferredAbilityCenter()
        self.evaluator = evaluator or PassEvaluator()
        self.answer_gate = answer_gate or PassAnswerGate()
        self.trace_store = trace_store
        self.shadow_reasoner = shadow_reasoner
        self.shadow_enabled = (
            bool(getattr(shadow_reasoner, "enabled", shadow_reasoner is not None))
            if shadow_enabled is None
            else bool(shadow_enabled)
        )
        self.tool_timeout_seconds = (
            float(get_settings().pipi_tool_timeout_seconds)
            if tool_timeout_seconds is None
            else float(tool_timeout_seconds)
        )
        self.max_iters = max_iters

    async def run(self, state: PipiState) -> PipiLoopResult:
        loop_started = perf_counter()
        trace: list[dict[str, Any]] = _initial_loop_trace(state)
        shadow_results: list[dict[str, Any]] = []
        provider_fallbacks: list[dict[str, Any]] = []
        current = state
        await self._record(
            "record_input_gate",
            current,
            current.metadata.get("input_gate_result") or {"intent": current.intent or current.intent_type},
        )
        await self._record("record_context_pack", current, current.context_pack)

        for iteration in range(1, self.max_iters + 1):
            decision = await _maybe_await(self.reasoner.next(current))
            decision_payload = _dump(decision)
            trace.append(
                {"iteration": iteration, "event": "reasoner_decision", "data": decision_payload}
            )
            await self._record("record_reasoner_decision", current, decision)
            provider_fallback = _provider_fallback_payload(decision_payload, iteration=iteration)
            if provider_fallback is not None:
                provider_fallbacks.append(provider_fallback)
                trace.append(
                    {
                        "iteration": iteration,
                        "event": "reasoner_provider_fallback",
                        "data": provider_fallback,
                        "payload": provider_fallback,
                    }
                )
                await self._record("record_event", "reasoner_provider_fallback", provider_fallback)
            shadow_result = await self._run_shadow_reasoner(
                current=current,
                decision=decision,
                iteration=iteration,
                trace=trace,
            )
            if shadow_result is not None:
                shadow_results.append(shadow_result)

            if isinstance(decision, AnswerDecision):
                gated = await _maybe_await(self.answer_gate.validate(current, decision))
                trace.append(
                    {"iteration": iteration, "event": "answer_gate_result", "data": _dump(gated)}
                )
                await self._record("record_answer_gate_result", current, gated)
                if not _gate_passed(gated):
                    return PipiLoopResult(
                        message="我还缺一点能直接拍板的依据。你补一句位置、口味或预算，我继续帮你收成一个。",
                        iterations=iteration,
                        finish_reason="answer_gate_failed",
                        trace=trace,
                        state=_state_payload(
                            current,
                            shadow_results,
                            provider_fallbacks,
                            total_latency_ms=_elapsed_ms(loop_started),
                        ),
                    )
                return PipiLoopResult(
                    message=decision.message,
                    ui_events=decision.ui_events,
                    data=decision.data,
                    iterations=iteration,
                    finish_reason="answer",
                    trace=trace,
                    state=_state_payload(
                        current,
                        shadow_results,
                        provider_fallbacks,
                        total_latency_ms=_elapsed_ms(loop_started),
                    ),
                )

            trace.append(
                {
                    "iteration": iteration,
                    "event": "tool_call",
                    "data": {
                        "tool_name": decision.tool_name,
                        "tool_args": decision.tool_args,
                        "reason": decision.reason,
                    },
                }
            )
            tool_started = perf_counter()
            tool_result = await self._call_tool_with_budget(decision, current)
            tool_latency_ms = _elapsed_ms(tool_started)
            trace.append(
                {
                    "iteration": iteration,
                    "event": "tool_result",
                    "data": {**_dump(tool_result), "tool_latency_ms": tool_latency_ms},
                }
            )
            await self._record("record_tool_result", current, decision, tool_result)

            eval_result = await _maybe_await(
                self.evaluator.evaluate_tool_result(
                    state=current,
                    decision=decision,
                    tool_result=tool_result,
                )
            )
            trace.append(
                {"iteration": iteration, "event": "evaluator_result", "data": _dump(eval_result)}
            )
            await self._record("record_evaluator_result", current, eval_result)
            current = current.append_tool_result(decision, tool_result, eval_result)

        return PipiLoopResult(
            message="我还缺一点能直接拍板的依据。你补一句位置、口味或预算，我继续帮你收成一个。",
            iterations=self.max_iters,
            finish_reason="max_iters",
            trace=trace,
            state=_state_payload(
                current,
                shadow_results,
                provider_fallbacks,
                total_latency_ms=_elapsed_ms(loop_started),
            ),
        )

    async def _run_shadow_reasoner(
        self,
        *,
        current: PipiState,
        decision: ReasonerDecision,
        iteration: int,
        trace: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not self.shadow_enabled or self.shadow_reasoner is None:
            return None

        deterministic_decision = _dump(decision)
        shadow_state = _shadow_state_snapshot(current)
        started = perf_counter()
        try:
            raw_result = await _maybe_await(
                self.shadow_reasoner.run_shadow(
                    context_pack=shadow_state,
                    deterministic_decision=decision,
                )
            )
            payload = _normalize_shadow_reasoner_result(
                raw_result,
                deterministic_decision=deterministic_decision,
                latency_ms=_elapsed_ms(started),
                shadow_reasoner=self.shadow_reasoner,
            )
        except Exception as exc:
            payload = _failed_shadow_reasoner_result(
                deterministic_decision=deterministic_decision,
                latency_ms=_elapsed_ms(started),
                shadow_reasoner=self.shadow_reasoner,
                error_message=str(exc),
            )

        trace.append(
            {
                "iteration": iteration,
                "event": "shadow_reasoner_result",
                "data": payload,
                "payload": payload,
            }
        )
        try:
            await self._record("record_shadow_reasoner_result", current, payload)
        except Exception as exc:
            payload["trace_store_error"] = str(exc)
        return payload

    async def _record(self, method_name: str, *args: Any) -> None:
        if self.trace_store is None:
            return
        method = getattr(self.trace_store, method_name, None)
        if method is not None:
            await _maybe_await(method(*args))

    async def _call_tool_with_budget(
        self,
        decision: ToolDecision,
        current: PipiState,
    ) -> ToolResult:
        try:
            result_or_awaitable = self.ability_center.call(
                decision.tool_name,
                decision.tool_args,
                state=current,
            )
            if not inspect.isawaitable(result_or_awaitable):
                return result_or_awaitable
            if self.tool_timeout_seconds > 0:
                return await asyncio.wait_for(result_or_awaitable, timeout=self.tool_timeout_seconds)
            return await result_or_awaitable
        except TimeoutError:
            return ToolResult(
                ok=False,
                tool_name=decision.tool_name,
                status="unavailable",
                data={
                    "timeout": True,
                    "timeout_seconds": self.tool_timeout_seconds,
                    "tool_args": decision.tool_args,
                },
                error_message=(
                    f"{decision.tool_name} timed out after "
                    f"{self.tool_timeout_seconds:g} seconds"
                ),
            )


class DeferredAbilityCenter:
    """Ability center stub that records a tool boundary without side effects."""

    async def call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        *,
        state: PipiState,
    ) -> ToolResult:
        return ToolResult(
            ok=True,
            tool_name=tool_name,
            status="skipped",
            data={
                "deferred": True,
                "tool_call": {
                    "name": tool_name,
                    "arguments": dict(tool_args),
                    "conversation_id": state.conversation_id,
                    "user_turn_id": state.turn_id,
                },
            },
        )


def _initial_loop_trace(state: PipiState) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    input_gate = state.metadata.get("input_gate_result")
    if isinstance(input_gate, dict):
        trace.append({"iteration": 0, "event": "input_gate_result", "data": input_gate})
    llm_query_rewrite = state.metadata.get("llm_query_rewrite")
    query_rewrite_selection = state.metadata.get("query_rewrite_selection")
    if isinstance(llm_query_rewrite, dict) or isinstance(query_rewrite_selection, dict):
        trace.append(
            {
                "iteration": 0,
                "event": "query_rewrite_result",
                "data": {
                    "llm_query_rewrite": llm_query_rewrite if isinstance(llm_query_rewrite, dict) else None,
                    "query_rewrite_selection": query_rewrite_selection
                    if isinstance(query_rewrite_selection, dict)
                    else None,
                },
            }
        )
    trace.append(
        {
            "iteration": 0,
            "event": "context_pack",
            "data": {
                "allowed_tools": list(state.allowed_tools),
                "context_pack": _dump(state.context_pack),
            },
        }
    )
    return trace


class PassEvaluator:
    def evaluate_tool_result(
        self,
        *,
        state: PipiState,
        decision: Any,
        tool_result: Any,
    ) -> dict[str, Any]:
        return {"passed": True, "quality_score": 1.0, "issues": []}


class PassAnswerGate:
    def validate(self, state: PipiState, decision: Any) -> dict[str, Any]:
        return {"passed": True, "issues": []}


def build_pipi_loop(**kwargs: Any) -> PipiLoop:
    return PipiLoop(**kwargs)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _dump(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_dump(item) for item in value]
    if isinstance(value, tuple):
        return [_dump(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _gate_passed(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(value.get("passed", True))
    return bool(getattr(value, "passed", True))


def _state_payload(
    state: PipiState,
    shadow_results: list[dict[str, Any]],
    provider_fallbacks: list[dict[str, Any]] | None = None,
    *,
    total_latency_ms: float | None = None,
) -> dict[str, Any]:
    payload = _dump(state)
    if total_latency_ms is not None:
        payload["total_latency_ms"] = total_latency_ms
    if shadow_results:
        payload["shadow_reasoner_results"] = list(shadow_results)
        payload["shadow_summary"] = _shadow_summary(shadow_results)
    if provider_fallbacks:
        payload["reasoner_provider_fallbacks"] = list(provider_fallbacks)
        payload["reasoner_provider_fallback_summary"] = _provider_fallback_summary(provider_fallbacks)
    return payload


def _provider_fallback_payload(
    decision_payload: dict[str, Any],
    *,
    iteration: int,
) -> dict[str, Any] | None:
    provider = decision_payload.get("llm_provider")
    status = decision_payload.get("llm_status")
    if provider is None or status not in {"fallback", "disabled"}:
        return None
    return {
        "provider": str(provider),
        "status": str(status),
        "error_type": str(decision_payload.get("llm_error_type") or status),
        "error": decision_payload.get("llm_error"),
        "iteration": iteration,
        "fallback_decision": _provider_decision_snapshot(decision_payload),
        "product_output_unchanged": True,
    }


def _provider_decision_snapshot(decision_payload: dict[str, Any]) -> dict[str, Any]:
    snapshot = {
        "type": decision_payload.get("type"),
        "tool_name": decision_payload.get("tool_name"),
        "message": decision_payload.get("message"),
    }
    return {key: value for key, value in snapshot.items() if value is not None}


def _provider_fallback_summary(provider_fallbacks: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = [str(item.get("status") or "unknown") for item in provider_fallbacks]
    error_types = [str(item.get("error_type") or "unknown") for item in provider_fallbacks]
    providers = [str(item.get("provider")) for item in provider_fallbacks if item.get("provider")]
    total = len(provider_fallbacks)
    fallbacks = statuses.count("fallback")
    disabled = statuses.count("disabled")
    schema_errors = error_types.count("schema_error")
    provider_errors = error_types.count("provider_error")
    timeouts = error_types.count("timeout")
    return {
        "enabled": True,
        "provider": providers[0] if providers else None,
        "calls": total,
        "fallbacks": fallbacks,
        "disabled": disabled,
        "schema_errors": schema_errors,
        "provider_errors": provider_errors,
        "timeouts": timeouts,
        "fallback_rate": _rate(fallbacks, total),
        "schema_error_rate": _rate(schema_errors, total),
        "provider_error_rate": _rate(provider_errors, total),
        "timeout_rate": _rate(timeouts, total),
        "product_output_unchanged": True,
    }


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _shadow_state_snapshot(state: PipiState) -> dict[str, Any]:
    snapshot = _dump(state.context_pack)
    if isinstance(snapshot, dict):
        return {
            **snapshot,
            "user_message": state.user_message,
            "allowed_tools": list(state.allowed_tools),
            "intent": state.intent or state.intent_type,
            "tool_results": _dump(state.tool_results),
        }
    return {"context_pack": snapshot, "user_message": state.user_message}


def _normalize_shadow_reasoner_result(
    raw_result: Any,
    *,
    deterministic_decision: dict[str, Any],
    latency_ms: float,
    shadow_reasoner: Any,
) -> dict[str, Any]:
    raw_payload = _dump(raw_result)
    try:
        result = ShadowReasonerResult.model_validate(raw_payload)
    except Exception as exc:
        payload = _failed_shadow_reasoner_result(
            deterministic_decision=deterministic_decision,
            latency_ms=latency_ms,
            shadow_reasoner=shadow_reasoner,
            error_message=f"invalid shadow result schema: {exc}",
        )
        payload["raw_shadow_result"] = raw_payload
        return payload
    return _shadow_trace_payload(result, deterministic_decision=deterministic_decision)


def _failed_shadow_reasoner_result(
    *,
    deterministic_decision: dict[str, Any],
    latency_ms: float,
    shadow_reasoner: Any,
    error_message: str,
) -> dict[str, Any]:
    result = ShadowReasonerResult(
        enabled=True,
        status="provider_error",
        provider=_shadow_attr(shadow_reasoner, "provider"),
        model=_shadow_attr(shadow_reasoner, "model"),
        decision_json=None,
        normalized_decision=None,
        error=error_message,
        latency_ms=latency_ms,
        schema_enforced=False,
        raw_mode="json_object_fallback",
    )
    return _shadow_trace_payload(result, deterministic_decision=deterministic_decision)


def _shadow_decision_schema_valid(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    decision_type = value.get("type")
    if decision_type == "answer":
        return isinstance(value.get("message"), str) and bool(value["message"].strip())
    if decision_type == "tool":
        return isinstance(value.get("tool_name"), str) and isinstance(
            value.get("tool_args", {}),
            dict,
        )
    if value.get("tool_name") is not None:
        return isinstance(value.get("tool_name"), str) and isinstance(
            value.get("tool_args", {}),
            dict,
        )
    return False


def _shadow_trace_payload(
    result: ShadowReasonerResult,
    *,
    deterministic_decision: dict[str, Any],
) -> dict[str, Any]:
    normalized = result.normalized_decision
    return {
        "enabled": result.enabled,
        "status": result.status,
        "provider": result.provider,
        "model": result.model,
        "deterministic_decision": deterministic_decision,
        "shadow_decision": normalized,
        "decision_json": result.decision_json,
        "schema_valid": result.status == "success" and isinstance(normalized, dict),
        "schema_enforced": result.schema_enforced,
        "schema_name": result.schema_name,
        "schema_version": result.schema_version,
        "raw_mode": result.raw_mode,
        "latency_ms": result.latency_ms,
        "error": result.error,
    }


def _shadow_attr(shadow_reasoner: Any, name: str) -> str:
    value = getattr(shadow_reasoner, name, None)
    if value is None:
        return "unknown"
    return str(value)


def _elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 3)


def _shadow_summary(shadow_results: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = [str(result.get("status") or "unknown") for result in shadow_results]
    providers = [str(result.get("provider")) for result in shadow_results if result.get("provider")]
    models = [str(result.get("model")) for result in shadow_results if result.get("model")]
    enabled_calls = [result for result in shadow_results if result.get("enabled") is True]
    return {
        "enabled": True,
        "provider": providers[0] if providers else None,
        "model": models[0] if models else None,
        "calls": len(enabled_calls),
        "schema_errors": statuses.count("schema_error"),
        "provider_errors": statuses.count("provider_error"),
        "timeouts": statuses.count("timeout"),
        "decision_mismatches": sum(
            1 for result in shadow_results if _shadow_decision_mismatch(result)
        ),
        "schema_valid_count": len(
            [result for result in shadow_results if result.get("schema_valid") is True]
        ),
        "structured_schema_enforced": any(
            result.get("schema_enforced") is True for result in shadow_results
        ),
        "raw_modes": sorted(
            {
                str(result.get("raw_mode"))
                for result in shadow_results
                if result.get("raw_mode") is not None
            }
        ),
        "implementation_boundary": (
            "shadow reasoner is audit-only and never calls tools; deterministic decisions "
            "continue to drive ToolCall, ui_events, and final answers"
        ),
    }


def _shadow_decision_mismatch(result: dict[str, Any]) -> bool:
    deterministic = result.get("deterministic_decision")
    shadow = result.get("shadow_decision")
    if not isinstance(deterministic, dict) or not isinstance(shadow, dict):
        return False
    if deterministic.get("type") != shadow.get("type"):
        return True
    if deterministic.get("type") == "tool":
        return deterministic.get("tool_name") != shadow.get("tool_name")
    if deterministic.get("type") == "answer":
        det_events = deterministic.get("ui_events")
        shadow_events = shadow.get("ui_events")
        return _event_type_signature(det_events) != _event_type_signature(shadow_events)
    return False


def _event_type_signature(events: Any) -> list[str]:
    if not isinstance(events, list):
        return []
    return [
        str(event.get("type"))
        for event in events
        if isinstance(event, dict) and event.get("type") is not None
    ]


def _context_pack_after_tool(
    context_pack: dict[str, Any],
    tool_result: ToolResult,
) -> dict[str, Any]:
    updated = dict(context_pack)
    data = dict(tool_result.data or {})
    if tool_result.tool_name == "search_knowledge":
        retrieval_run = data.get("retrieval_run")
        hits = data.get("retrieval_hits") or data.get("hits")
        if isinstance(retrieval_run, dict):
            updated["retrieval_run"] = retrieval_run
            if not hits:
                hits = retrieval_run.get("hits")
        if isinstance(hits, list):
            updated["retrieval_hits"] = hits
            updated["strongest_evidence"] = hits
        if isinstance(data.get("evidence_pack"), dict):
            updated["evidence_pack"] = data["evidence_pack"]
        if isinstance(data.get("context"), dict):
            updated["context"] = data["context"]
        if isinstance(data.get("query_rewrite"), dict):
            updated["query_rewrite"] = data["query_rewrite"]
    elif data:
        outputs = dict(updated.get("tool_outputs") or {})
        outputs[tool_result.tool_name] = data
        updated["tool_outputs"] = outputs
    return updated


__all__ = [
    "AbilityCenter",
    "DeferredAbilityCenter",
    "DeterministicReasoner",
    "PassAnswerGate",
    "PassEvaluator",
    "PipiLoop",
    "PipiState",
    "Reasoner",
    "ShadowReasoner",
    "build_pipi_loop",
]
