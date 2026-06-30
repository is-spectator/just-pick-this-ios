from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

HarnessTraceEventName = Literal[
    "input_gate_result",
    "context_pack",
    "reasoner_decision",
    "reasoner_provider_fallback",
    "shadow_reasoner_result",
    "tool_call",
    "tool_result",
    "evaluator_result",
    "answer_gate_result",
]


class AgentSchema(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True, str_strip_whitespace=True)


class ToolDecision(AgentSchema):
    type: Literal["tool"] = "tool"
    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    reason: str


class AnswerDecision(AgentSchema):
    type: Literal["answer"] = "answer"
    message: str
    ui_events: list[dict[str, Any]] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)


ReasonerDecision = Annotated[ToolDecision | AnswerDecision, Field(discriminator="type")]
REASONER_DECISION_SCHEMA_NAME = "pipi_reasoner_decision"
REASONER_DECISION_SCHEMA_VERSION = "v1"
ToolResultStatus = Literal["succeeded", "failed", "skipped", "denied", "unavailable"]
ShadowReasonerStatus = Literal[
    "disabled",
    "success",
    "schema_error",
    "provider_error",
    "timeout",
]
ShadowRawMode = Literal["structured_output", "json_object_fallback", "mock"]


class ToolResult(AgentSchema):
    ok: bool
    tool_name: str
    status: ToolResultStatus = "succeeded"
    data: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None


class ShadowReasonerResult(AgentSchema):
    enabled: bool
    status: ShadowReasonerStatus
    provider: str | None = None
    model: str | None = None
    decision_json: dict[str, Any] | None = None
    normalized_decision: dict[str, Any] | None = None
    error: str | None = None
    latency_ms: float | None = None
    schema_enforced: bool = False
    schema_name: str | None = REASONER_DECISION_SCHEMA_NAME
    schema_version: str = REASONER_DECISION_SCHEMA_VERSION
    raw_mode: ShadowRawMode = "mock"


class HarnessTraceEvent(AgentSchema):
    event: HarnessTraceEventName
    payload: dict[str, Any] = Field(default_factory=dict)
    sequence_index: int | None = None
    recorded_at: str | None = None


class PipiLoopResult(AgentSchema):
    message: str
    ui_events: list[dict[str, Any]] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    iterations: int
    finish_reason: Literal["answer", "max_iters", "answer_gate_failed"]
    trace: list[dict[str, Any]] = Field(default_factory=list)
    state: dict[str, Any] = Field(default_factory=dict)


def reasoner_decision_json_schema(*, strict: bool = True) -> dict[str, Any]:
    schema = TypeAdapter(ReasonerDecision).json_schema()
    if strict:
        _forbid_additional_properties(schema)
    return schema


def _forbid_additional_properties(value: Any) -> None:
    if isinstance(value, dict):
        if value.get("type") == "object":
            value.setdefault("additionalProperties", False)
        for item in value.values():
            _forbid_additional_properties(item)
    elif isinstance(value, list):
        for item in value:
            _forbid_additional_properties(item)


__all__ = [
    "AgentSchema",
    "AnswerDecision",
    "HarnessTraceEvent",
    "HarnessTraceEventName",
    "PipiLoopResult",
    "REASONER_DECISION_SCHEMA_NAME",
    "REASONER_DECISION_SCHEMA_VERSION",
    "ReasonerDecision",
    "ShadowReasonerResult",
    "ShadowRawMode",
    "ShadowReasonerStatus",
    "ToolDecision",
    "ToolResult",
    "ToolResultStatus",
    "reasoner_decision_json_schema",
]
