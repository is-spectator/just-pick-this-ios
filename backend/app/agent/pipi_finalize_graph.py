"""Deterministic PipiFinalizeGraph V0.

The finalize graph runs after a help card has collected human answers.  V0 is
intentionally deterministic and service-friendly: it can call injected tool or
repository interfaces, but it does not implement persistence, retrieval, or a
real LLM connection here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal, NotRequired, Protocol, TypedDict, runtime_checkable


FinalizeStatus = Literal["pending", "final_ready", "needs_more_answers", "failed"]
ToolStatus = Literal["succeeded", "unavailable", "failed"]


class HelpCardSnapshot(TypedDict, total=False):
    """Serializable help card shape used by PipiFinalizeGraph V0."""

    id: str
    conversation_id: str
    user_id: str
    title: str
    context_text: str
    min_answers_required: int
    status: str
    metadata: dict[str, Any]


class HelpAnswerSnapshot(TypedDict, total=False):
    """Serializable human answer shape used by PipiFinalizeGraph V0."""

    id: str
    help_card_id: str
    user_id: str
    text: str
    status: str
    metadata: dict[str, Any]


class RetrievalHit(TypedDict, total=False):
    """Knowledge hit shape ready to map to future retrieval_hit rows."""

    source_id: str
    title: str
    score: float
    payload: dict[str, Any]


class RetrievalRun(TypedDict, total=False):
    """Knowledge retrieval summary ready to map to future retrieval_run rows."""

    id: str
    query: str
    hits: list[RetrievalHit]
    metadata: dict[str, Any]


class FinalAnswerDecision(TypedDict, total=False):
    """Deterministic final answer decision before tool persistence."""

    kind: Literal["final_recommendation", "needs_more_answers"]
    title: str
    subtitle: str
    reason: str
    bullets: list[str]
    warning: str
    confidence: float
    place_key: str
    item_key: str
    evidence_answer_ids: list[str]
    followups: list[str]
    metadata: dict[str, Any]


class ToolCallRecord(TypedDict, total=False):
    """Tool call attempt recorded in graph state."""

    name: str
    arguments: dict[str, Any]
    status: ToolStatus
    result: dict[str, Any]
    error: str


class PipiFinalizeGraphState(TypedDict):
    """State carried through PipiFinalizeGraph V0."""

    help_card_id: str
    conversation_id: NotRequired[str]
    user_id: NotRequired[str]
    help_card: NotRequired[HelpCardSnapshot]
    help_answers: NotRequired[list[HelpAnswerSnapshot]]
    retrieval_run: NotRequired[RetrievalRun]
    retrieval_hits: NotRequired[list[RetrievalHit]]
    final_answer: NotRequired[FinalAnswerDecision]
    final_recommendation_card: NotRequired[dict[str, Any]]
    intent_answer: NotRequired[dict[str, Any]]
    light_event: NotRequired[dict[str, Any]]
    tool_calls: NotRequired[list[ToolCallRecord]]
    status: NotRequired[FinalizeStatus]
    warnings: NotRequired[list[str]]
    metadata: NotRequired[dict[str, Any]]


@runtime_checkable
class FinalizeRepository(Protocol):
    """Future persistence boundary for help cards and answers."""

    def load_help_card(self, help_card_id: str) -> Mapping[str, Any] | None:
        """Return a persisted help card snapshot."""

    def load_help_answers(self, help_card_id: str) -> Sequence[Mapping[str, Any]]:
        """Return accumulated help answers for the card."""


@runtime_checkable
class KnowledgeRetriever(Protocol):
    """Future retrieval boundary for persisted knowledge runs."""

    def retrieve(self, query: str, *, limit: int = 5) -> Mapping[str, Any]:
        """Return retrieval run data for a query."""


@runtime_checkable
class ToolInvoker(Protocol):
    """Future tool/function-call boundary."""

    def invoke_tool(
        self,
        name: str,
        arguments: Mapping[str, Any],
        state: PipiFinalizeGraphState,
    ) -> Mapping[str, Any]:
        """Invoke a named tool and return a serializable payload."""


ToolCallable = Callable[[str, Mapping[str, Any], PipiFinalizeGraphState], Mapping[str, Any]]


class PipiFinalizeGraph:
    """Small deterministic graph runner for finalizing 求一个 answers."""

    node_order = (
        "load_help_card",
        "load_help_answers",
        "retrieve_knowledge",
        "decide_final_answer",
        "create_final_recommendation_card",
        "save_intent_answer",
        "light_user",
    )

    def __init__(
        self,
        *,
        repository: FinalizeRepository | None = None,
        retriever: KnowledgeRetriever | None = None,
        tools: ToolInvoker | Mapping[str, Callable[..., Mapping[str, Any]]] | ToolCallable | None = None,
        min_answers_required: int = 3,
    ) -> None:
        self.repository = repository
        self.retriever = retriever
        self.tools = tools
        self.min_answers_required = min_answers_required

    def invoke(self, state: PipiFinalizeGraphState) -> PipiFinalizeGraphState:
        """Run all V0 nodes in order."""

        current = _copy_state(state)
        for node_name in self.node_order:
            current = getattr(self, node_name)(current)
        return current

    run = invoke

    def load_help_card(self, state: PipiFinalizeGraphState) -> PipiFinalizeGraphState:
        """Load or normalize the help card snapshot."""

        if "help_card" in state:
            return state

        loaded: Mapping[str, Any] | None = None
        if self.repository is not None:
            loaded = self.repository.load_help_card(state["help_card_id"])

        if loaded is None:
            loaded = {
                "id": state["help_card_id"],
                "conversation_id": state.get("conversation_id", ""),
                "user_id": state.get("user_id", ""),
                "title": "",
                "context_text": "",
                "min_answers_required": self.min_answers_required,
                "status": "collecting",
            }

        help_card = _normalize_help_card(loaded, state["help_card_id"])
        return {
            **state,
            "help_card": help_card,
            "conversation_id": state.get("conversation_id") or help_card.get("conversation_id", ""),
            "user_id": state.get("user_id") or help_card.get("user_id", ""),
        }

    def load_help_answers(self, state: PipiFinalizeGraphState) -> PipiFinalizeGraphState:
        """Load or normalize accumulated human answers."""

        if "help_answers" in state:
            answers = [_normalize_help_answer(answer, state["help_card_id"]) for answer in state["help_answers"]]
            return {**state, "help_answers": answers}

        loaded: Sequence[Mapping[str, Any]] = ()
        if self.repository is not None:
            loaded = self.repository.load_help_answers(state["help_card_id"])

        return {
            **state,
            "help_answers": [
                _normalize_help_answer(answer, state["help_card_id"]) for answer in loaded
            ],
        }

    def retrieve_knowledge(self, state: PipiFinalizeGraphState) -> PipiFinalizeGraphState:
        """Retrieve knowledge through an injected interface or produce a V0 run."""

        query = _combined_text(state)
        if self.retriever is not None and query.strip():
            run = dict(self.retriever.retrieve(query, limit=5))
        else:
            run = _deterministic_retrieval(query)

        hits = list(run.get("hits", []))
        return {**state, "retrieval_run": run, "retrieval_hits": hits}

    def decide_final_answer(self, state: PipiFinalizeGraphState) -> PipiFinalizeGraphState:
        """Choose a final answer without using a real LLM."""

        answers = state.get("help_answers", [])
        min_required = int(state.get("help_card", {}).get("min_answers_required") or self.min_answers_required)
        if len(answers) < min_required:
            return {
                **state,
                "status": "needs_more_answers",
                "final_answer": {
                    "kind": "needs_more_answers",
                    "reason": f"Need {min_required} answers before finalization.",
                    "evidence_answer_ids": [answer.get("id", "") for answer in answers if answer.get("id")],
                },
            }

        text = _combined_text(state)
        evidence_ids = [answer.get("id", "") for answer in answers if answer.get("id")]
        if _is_korea_small_myeongdong_case(text):
            decision: FinalAnswerDecision = {
                "kind": "final_recommendation",
                "title": "圣水洞小店街区",
                "subtitle": "不去明洞,先去圣水。",
                "reason": "真人回答已经把方向收敛到更小众、更好逛的街区。",
                "bullets": ["游客感更弱", "小店和咖啡密度高", "适合边逛边调整"],
                "warning": "只想买热门美妆时别选。",
                "confidence": 0.76,
                "place_key": "korea-seongsu",
                "item_key": "shopping-street",
                "evidence_answer_ids": evidence_ids,
                "followups": ["为什么?", "换个小众的"],
                "metadata": {"deterministic_rule": "korea_small_myeongdong_to_seongsu"},
            }
        else:
            decision = {
                "kind": "final_recommendation",
                "title": "先选真人答案最集中的那个",
                "subtitle": "答案已经够了,按共识走。",
                "reason": "累计回答达到阈值,但 V0 没有命中特定领域规则。",
                "bullets": ["优先采用重复出现的地点或选项", "保留真人证据", "后续可接知识库增强"],
                "warning": "V0 规则未绑定具体领域图片资产。",
                "confidence": 0.62,
                "place_key": "generic-final-choice",
                "item_key": "human-consensus",
                "evidence_answer_ids": evidence_ids,
                "followups": ["为什么?"],
                "metadata": {"deterministic_rule": "generic_consensus_fallback"},
            }

        return {**state, "status": "pending", "final_answer": decision}

    def create_final_recommendation_card(
        self,
        state: PipiFinalizeGraphState,
    ) -> PipiFinalizeGraphState:
        """Create the final recommendation card through the tool boundary."""

        decision = state.get("final_answer", {})
        if decision.get("kind") != "final_recommendation":
            return state

        arguments = {
            "help_card_id": state["help_card_id"],
            "conversation_id": state.get("conversation_id", ""),
            "user_id": state.get("user_id", ""),
            "source": "pipi_finalized_from_help",
            **decision,
        }
        tool_record = self._call_tool("create_final_recommendation_card", arguments, state)
        card = dict(tool_record.get("result") or {})
        if not card:
            card = {
                "id": f"final-card:{state['help_card_id']}",
                "source": "pipi_finalized_from_help",
                "status": "draft",
                **arguments,
            }

        return _append_tool_call({**state, "final_recommendation_card": card}, tool_record)

    def save_intent_answer(self, state: PipiFinalizeGraphState) -> PipiFinalizeGraphState:
        """Save the final answer summary through the tool boundary."""

        decision = state.get("final_answer", {})
        if decision.get("kind") != "final_recommendation":
            return state

        arguments = {
            "help_card_id": state["help_card_id"],
            "conversation_id": state.get("conversation_id", ""),
            "answer_text": f"{decision.get('subtitle', '')} {decision.get('reason', '')}".strip(),
            "evidence_answer_ids": decision.get("evidence_answer_ids", []),
            "metadata": decision.get("metadata", {}),
        }
        tool_record = self._call_tool("save_intent_answer", arguments, state)
        intent_answer = dict(tool_record.get("result") or {})
        if not intent_answer:
            intent_answer = {
                "id": f"intent-answer:{state['help_card_id']}",
                "status": "draft",
                **arguments,
            }

        return _append_tool_call({**state, "intent_answer": intent_answer}, tool_record)

    def light_user(self, state: PipiFinalizeGraphState) -> PipiFinalizeGraphState:
        """Create a final-ready light event through the tool boundary."""

        decision = state.get("final_answer", {})
        if decision.get("kind") != "final_recommendation":
            return state

        card = state.get("final_recommendation_card", {})
        arguments = {
            "target_type": "card",
            "target_id": card.get("id", state["help_card_id"]),
            "help_card_id": state["help_card_id"],
            "conversation_id": state.get("conversation_id", ""),
            "user_id": state.get("user_id", ""),
            "type": "final_ready",
            "title": "有人帮你选好了",
            "body": f"{decision.get('title', '求一个')} 有结果了。",
        }
        tool_record = self._call_tool("light_user", arguments, state)
        light_event = dict(tool_record.get("result") or {})
        if not light_event:
            light_event = {
                "id": f"light-event:{state['help_card_id']}",
                "status": "draft",
                **arguments,
            }

        return _append_tool_call(
            {**state, "light_event": light_event, "status": "final_ready"},
            tool_record,
        )

    def _call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any],
        state: PipiFinalizeGraphState,
    ) -> ToolCallRecord:
        try:
            if self.tools is None:
                return {
                    "name": name,
                    "arguments": dict(arguments),
                    "status": "unavailable",
                    "result": {},
                }

            if hasattr(self.tools, "invoke_tool"):
                result = self.tools.invoke_tool(name, arguments, state)  # type: ignore[union-attr]
            elif isinstance(self.tools, Mapping):
                handler = self.tools.get(name)
                if handler is None:
                    return {
                        "name": name,
                        "arguments": dict(arguments),
                        "status": "unavailable",
                        "result": {},
                    }
                result = handler(**dict(arguments))
            else:
                result = self.tools(name, arguments, state)

            return {
                "name": name,
                "arguments": dict(arguments),
                "status": "succeeded",
                "result": dict(result or {}),
            }
        except Exception as exc:  # pragma: no cover - defensive boundary for external tools.
            return {
                "name": name,
                "arguments": dict(arguments),
                "status": "failed",
                "result": {},
                "error": str(exc),
            }


def build_pipi_finalize_graph(**kwargs: Any) -> PipiFinalizeGraph:
    """Return a deterministic V0 graph object."""

    return PipiFinalizeGraph(**kwargs)


def load_help_card(state: PipiFinalizeGraphState) -> PipiFinalizeGraphState:
    return PipiFinalizeGraph().load_help_card(state)


def load_help_answers(state: PipiFinalizeGraphState) -> PipiFinalizeGraphState:
    return PipiFinalizeGraph().load_help_answers(state)


def retrieve_knowledge(state: PipiFinalizeGraphState) -> PipiFinalizeGraphState:
    return PipiFinalizeGraph().retrieve_knowledge(state)


def decide_final_answer(state: PipiFinalizeGraphState) -> PipiFinalizeGraphState:
    return PipiFinalizeGraph().decide_final_answer(state)


def create_final_recommendation_card(
    state: PipiFinalizeGraphState,
) -> PipiFinalizeGraphState:
    return PipiFinalizeGraph().create_final_recommendation_card(state)


def save_intent_answer(state: PipiFinalizeGraphState) -> PipiFinalizeGraphState:
    return PipiFinalizeGraph().save_intent_answer(state)


def light_user(state: PipiFinalizeGraphState) -> PipiFinalizeGraphState:
    return PipiFinalizeGraph().light_user(state)


def _copy_state(state: PipiFinalizeGraphState) -> PipiFinalizeGraphState:
    return {**state, "tool_calls": list(state.get("tool_calls", []))}


def _normalize_help_card(card: Mapping[str, Any], fallback_id: str) -> HelpCardSnapshot:
    return {
        "id": str(card.get("id") or card.get("help_card_id") or fallback_id),
        "conversation_id": str(card.get("conversation_id") or ""),
        "user_id": str(card.get("user_id") or card.get("owner_user_id") or ""),
        "title": str(card.get("title") or ""),
        "context_text": str(card.get("context_text") or card.get("contextText") or ""),
        "min_answers_required": int(card.get("min_answers_required") or card.get("minAnswersRequired") or 3),
        "status": str(card.get("status") or "collecting"),
        "metadata": dict(card.get("metadata") or {}),
    }


def _normalize_help_answer(answer: Mapping[str, Any], help_card_id: str) -> HelpAnswerSnapshot:
    return {
        "id": str(answer.get("id") or answer.get("answer_id") or ""),
        "help_card_id": str(answer.get("help_card_id") or answer.get("helpCardId") or help_card_id),
        "user_id": str(answer.get("user_id") or answer.get("answer_user_id") or ""),
        "text": str(answer.get("text") or answer.get("raw_text") or answer.get("rawText") or ""),
        "status": str(answer.get("status") or "collected"),
        "metadata": dict(answer.get("metadata") or {}),
    }


def _combined_text(state: PipiFinalizeGraphState) -> str:
    help_card = state.get("help_card", {})
    answers = state.get("help_answers", [])
    parts = [
        str(help_card.get("title", "")),
        str(help_card.get("context_text", "")),
        " ".join(answer.get("text", "") for answer in answers),
    ]
    return " ".join(part for part in parts if part).strip()


def _deterministic_retrieval(query: str) -> RetrievalRun:
    hits: list[RetrievalHit] = []
    if _is_korea_small_myeongdong_case(query) or "圣水" in query:
        hits.append(
            {
                "source_id": "deterministic:korea-seongsu",
                "title": "圣水适合替代明洞的小众逛街路线",
                "score": 0.91,
                "payload": {
                    "place_key": "korea-seongsu",
                    "item_key": "shopping-street",
                    "evidence": "V0 curated rule for Korea/Myeongdong/small-shop requests.",
                },
            }
        )

    return {
        "id": "retrieval:deterministic-finalize-v0",
        "query": query,
        "hits": hits,
        "metadata": {"provider": "deterministic_v0"},
    }


def _is_korea_small_myeongdong_case(text: str) -> bool:
    return "韩国" in text and "明洞" in text and ("小众" in text or "圣水" in text)


def _append_tool_call(
    state: PipiFinalizeGraphState,
    record: ToolCallRecord,
) -> PipiFinalizeGraphState:
    return {**state, "tool_calls": [*state.get("tool_calls", []), record]}


__all__ = [
    "FinalAnswerDecision",
    "FinalizeRepository",
    "HelpAnswerSnapshot",
    "HelpCardSnapshot",
    "KnowledgeRetriever",
    "PipiFinalizeGraph",
    "PipiFinalizeGraphState",
    "RetrievalHit",
    "RetrievalRun",
    "ToolCallRecord",
    "ToolInvoker",
    "build_pipi_finalize_graph",
    "create_final_recommendation_card",
    "decide_final_answer",
    "light_user",
    "load_help_answers",
    "load_help_card",
    "retrieve_knowledge",
    "save_intent_answer",
]
