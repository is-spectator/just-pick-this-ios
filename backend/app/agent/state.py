"""Shared state and protocol types for the Pipi chat graph V0."""

from __future__ import annotations

from typing import Any, Literal, NotRequired, Protocol, TypedDict, runtime_checkable


PipiIntent = Literal[
    "greeting",
    "smalltalk",
    "app_help",
    "decision_request",
    "help_request",
    "update_help_card",
    "publish_help",
    "one_liner_answer",
    "finalize_request",
    "unknown",
]
PipiNextAction = Literal["respond", "call_tool"]
PipiToolName = Literal[
    "search_knowledge",
    "create_recommendation_card",
    "draft_help_card",
    "update_help_card",
    "publish_help_card",
    "submit_one_liner_answer",
    "save_intent_answer",
    "light_user",
    "finalize_help_card",
]
ToolExecutionStatus = Literal["skipped", "unavailable", "succeeded", "failed"]
PipiHarnessEventName = Literal[
    "input_gate_result",
    "query_rewrite_result",
    "context_pack",
    "reasoner_decision",
    "tool_call",
    "tool_result",
    "evaluator_result",
    "answer_gate_result",
]


class ChatTurn(TypedDict, total=False):
    """Persisted conversation turn shape used by graph V0."""

    id: str
    conversation_id: str
    role: Literal["user", "assistant", "tool"]
    content: str
    metadata: dict[str, Any]


class ContextSnapshot(TypedDict, total=False):
    """Small deterministic context bundle built before retrieval."""

    conversation_id: str
    user_turn_id: str
    user_message: str
    recent_turns: list[ChatTurn]
    facts: dict[str, Any]


class RetrievalHit(TypedDict, total=False):
    """Knowledge retrieval hit, ready to map to future retrieval_hit rows."""

    source_id: str
    title: str
    score: float
    payload: dict[str, Any]


class RetrievalRun(TypedDict, total=False):
    """Knowledge retrieval run summary, ready to map to future retrieval_run rows."""

    id: str
    query: str
    hits: list[RetrievalHit]
    metadata: dict[str, Any]


class EvidenceEvaluation(TypedDict):
    """Structured evidence gate output persisted with the agent run."""

    can_recommend: bool
    confidence: float
    missing_requirements: list[str]
    reason: str


class QueryRewrite(TypedDict, total=False):
    """Query rewritten after context assembly and before intent classification."""

    original: str
    rewritten: str
    changed: bool
    method: str
    reason: str
    entities: dict[str, Any]


class HarnessTraceEvent(TypedDict, total=False):
    """Standard Hybrid Harness event persisted in AgentRun loop_trace."""

    event: PipiHarnessEventName
    name: PipiHarnessEventName
    type: PipiHarnessEventName
    stage: str
    sequence_index: int
    recorded_at: str
    payload: dict[str, Any]
    data: dict[str, Any]


class ToolCallDraft(TypedDict, total=False):
    """Single function/tool call selected by the deterministic adapter."""

    name: PipiToolName
    arguments: dict[str, Any]
    reason: str


class ToolExecutionResult(TypedDict, total=False):
    """Result from executing, skipping, or deferring a selected tool call."""

    status: ToolExecutionStatus
    name: str
    result: dict[str, Any]
    error: str


class PipiChatGraphState(TypedDict):
    """State carried by PipiChatGraph V0.

    The graph is intentionally deterministic and database-friendly: callers can
    provide already-persisted turn identifiers, and future persistence services
    can enrich the state without changing node contracts.
    """

    conversation_id: str
    user_turn_id: str
    user_message: str

    agent_run_id: NotRequired[str]
    input_gate_result: NotRequired[dict[str, Any]]
    query_rewrite: NotRequired[QueryRewrite]
    intent: NotRequired[PipiIntent]
    context: NotRequired[ContextSnapshot]
    context_pack: NotRequired[dict[str, Any]]
    allowed_tools: NotRequired[list[str]]
    retrieval_run: NotRequired[RetrievalRun]
    retrieval_hits: NotRequired[list[RetrievalHit]]
    evidence_evaluation: NotRequired[EvidenceEvaluation]
    next_action: NotRequired[PipiNextAction]
    tool_call: NotRequired[ToolCallDraft]
    tool_execution: NotRequired[ToolExecutionResult]
    assistant_message: NotRequired[str]
    loop_trace: NotRequired[list[HarnessTraceEvent]]
    metadata: NotRequired[dict[str, Any]]


@runtime_checkable
class ConversationContextProvider(Protocol):
    """Future service boundary for loading recent conversation context."""

    def build_context(self, state: PipiChatGraphState) -> ContextSnapshot:
        """Return a context snapshot for the current user turn."""


@runtime_checkable
class KnowledgeRetriever(Protocol):
    """Future service boundary for persisted knowledge retrieval."""

    def retrieve(self, state: PipiChatGraphState) -> RetrievalRun:
        """Return retrieval run data for the current user turn."""


@runtime_checkable
class ToolExecutor(Protocol):
    """Future service boundary for persisted tool/function execution."""

    def execute(self, tool_call: ToolCallDraft, state: PipiChatGraphState) -> ToolExecutionResult:
        """Execute one tool call and return a serializable result."""
