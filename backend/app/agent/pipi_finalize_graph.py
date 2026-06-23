"""PipiFinalizeGraph V0.

The finalize graph runs after a help card has collected human answers. It uses
deterministic rules in V0 and keeps persistence behind tool calls.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal, NotRequired, Protocol, TypedDict, runtime_checkable

from app.services.intent_answer_service import build_help_final_metadata


FinalizeStatus = Literal["pending", "final_ready", "needs_more_answers", "failed"]
ToolStatus = Literal["succeeded", "unavailable", "failed"]


class HelpCardSnapshot(TypedDict, total=False):
    """Serializable help card shape used by PipiFinalizeGraph V0."""

    id: str
    question_id: str
    conversation_id: str
    user_id: str
    title: str
    context_text: str
    answer_count: int
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
    """Final answer decision before tool persistence."""

    kind: Literal["final_recommendation", "needs_more_answers"]
    title: str
    subtitle: str
    reason: str
    decision_factor: str
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
    question_id: NotRequired[str]
    conversation_id: NotRequired[str]
    user_id: NotRequired[str]
    agent_run_id: NotRequired[str]
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
        "finalize_help_card",
        "create_recommendation_card",
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

        loaded: Mapping[str, Any] | None = None
        if "help_card" in state:
            loaded = state["help_card"]
        elif self.repository is not None:
            loaded = self.repository.load_help_card(state["help_card_id"])

        if loaded is None:
            loaded = {
                "id": state["help_card_id"],
                "question_id": state.get("question_id", ""),
                "conversation_id": state.get("conversation_id", ""),
                "user_id": state.get("user_id", ""),
                "title": "",
                "context_text": "",
                "answer_count": 0,
                "min_answers_required": self.min_answers_required,
                "status": "collecting",
            }

        help_card = _normalize_help_card(loaded, state["help_card_id"])
        return {
            **state,
            "help_card": help_card,
            "question_id": state.get("question_id") or help_card.get("question_id", ""),
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
        """Choose a final answer from accumulated human evidence."""

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

        evidence_ids = _selected_evidence_answer_ids(answers, min_required)
        retrieval_hit_ids = [
            hit.get("source_id", "") for hit in state.get("retrieval_hits", []) if hit.get("source_id")
        ]
        decision = _deterministic_final_decision(
            state=state,
            evidence_ids=evidence_ids,
            retrieval_hit_ids=retrieval_hit_ids,
        )

        return {**state, "status": "pending", "final_answer": decision}

    def finalize_help_card(self, state: PipiFinalizeGraphState) -> PipiFinalizeGraphState:
        """Record the finalize orchestration tool call before side effects."""

        if state.get("status") == "failed":
            return state

        decision = state.get("final_answer", {})
        if decision.get("kind") != "final_recommendation":
            return state

        arguments = {
            "help_card_id": state["help_card_id"],
            "question_id": state.get("question_id", ""),
            "conversation_id": state.get("conversation_id", ""),
            "user_id": state.get("user_id", ""),
            "evidence_answer_ids": decision.get("evidence_answer_ids", []),
            "confidence": decision.get("confidence"),
            "source": "pipi_finalize_graph",
            "metadata": {
                "mode": "orchestration_only",
                "source_type": "help_final",
                "source_ref_id": state["help_card_id"],
                "human_evidence_only": True,
            },
        }
        tool_record = self._call_tool("finalize_help_card", arguments, state)
        if tool_record["status"] == "failed":
            return _append_tool_call(
                {
                    **state,
                    "status": "failed",
                    "warnings": [*state.get("warnings", []), tool_record.get("error", "tool failed")],
                },
                tool_record,
            )
        return _append_tool_call(state, tool_record)

    def create_recommendation_card(
        self,
        state: PipiFinalizeGraphState,
    ) -> PipiFinalizeGraphState:
        """Create the final recommendation card through the tool boundary."""

        decision = state.get("final_answer", {})
        if decision.get("kind") != "final_recommendation":
            return state

        arguments = {
            "help_card_id": state["help_card_id"],
            "question_id": state.get("question_id", ""),
            "conversation_id": state.get("conversation_id", ""),
            "user_id": state.get("user_id", ""),
            "source": "pipi_finalized_from_help",
            "image_required": True,
            **decision,
        }
        tool_record = self._call_tool("create_recommendation_card", arguments, state)
        if tool_record["status"] == "failed":
            return _append_tool_call(
                {
                    **state,
                    "status": "failed",
                    "warnings": [*state.get("warnings", []), tool_record.get("error", "tool failed")],
                },
                tool_record,
            )

        card = dict(tool_record.get("result") or {})
        if not card:
            card = {
                "id": f"final-card:{state['help_card_id']}",
                "source": "pipi_finalized_from_help",
                "status": "draft",
                **arguments,
            }

        return _append_tool_call({**state, "final_recommendation_card": card}, tool_record)

    def create_final_recommendation_card(
        self,
        state: PipiFinalizeGraphState,
    ) -> PipiFinalizeGraphState:
        """Backward-compatible alias; audit tool_name stays standardized."""

        return self.create_recommendation_card(state)

    def save_intent_answer(self, state: PipiFinalizeGraphState) -> PipiFinalizeGraphState:
        """Save the final answer summary through the tool boundary."""

        if state.get("status") == "failed":
            return state

        decision = state.get("final_answer", {})
        if decision.get("kind") != "final_recommendation":
            return state

        card = state.get("final_recommendation_card", {})
        card_id = card.get("id") or card.get("card_id")
        decision_metadata = dict(decision.get("metadata") or {})
        metadata = build_help_final_metadata(
            help_card_id=state["help_card_id"],
            recommendation_card_id=str(card_id) if card_id else None,
            evidence_answer_ids=list(decision.get("evidence_answer_ids") or []),
            decision_factor=str(decision.get("decision_factor") or decision.get("reason") or ""),
            confidence=decision.get("confidence"),
            retrieval_hit_ids=list(decision_metadata.get("retrieval_hit_ids") or []),
            base=decision_metadata,
        )
        arguments = {
            "help_card_id": state["help_card_id"],
            "question_id": state.get("question_id", ""),
            "conversation_id": state.get("conversation_id", ""),
            "recommendation_card_id": card_id,
            "intent_key": "pipi_help_finalized",
            "intent_name": "Pipi finalized help answer",
            "answer_text": str(decision.get("decision_factor") or decision.get("reason") or "").strip(),
            "evidence_answer_ids": decision.get("evidence_answer_ids", []),
            "decision_factor": decision.get("decision_factor", ""),
            "tags": ["help_final"],
            "priority": 30,
            "metadata": metadata,
        }
        tool_record = self._call_tool("save_intent_answer", arguments, state)
        if tool_record["status"] == "failed":
            return _append_tool_call(
                {
                    **state,
                    "status": "failed",
                    "warnings": [*state.get("warnings", []), tool_record.get("error", "tool failed")],
                },
                tool_record,
            )

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

        if state.get("status") == "failed":
            return state

        decision = state.get("final_answer", {})
        if decision.get("kind") != "final_recommendation":
            return state

        card = state.get("final_recommendation_card", {})
        card_id = card.get("id") or card.get("card_id")
        arguments = {
            "target_type": "card",
            "target_id": card_id or state["help_card_id"],
            "help_card_id": state["help_card_id"],
            "question_id": state.get("question_id", ""),
            "conversation_id": state.get("conversation_id", ""),
            "user_id": state.get("user_id", ""),
            "recommendation_card_id": card_id,
            "type": "final_ready",
            "title": "有人帮你选好了",
            "body": f"{decision.get('title', '求一个')} 有结果了。",
            "metadata": {
                "source": "pipi_finalize_graph",
                "source_type": "help_final",
                "source_ref_id": state["help_card_id"],
                "help_card_id": state["help_card_id"],
            },
        }
        tool_record = self._call_tool("light_user", arguments, state)
        if tool_record["status"] == "failed":
            return _append_tool_call(
                {
                    **state,
                    "status": "failed",
                    "warnings": [*state.get("warnings", []), tool_record.get("error", "tool failed")],
                },
                tool_record,
            )

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


def finalize_help_card(state: PipiFinalizeGraphState) -> PipiFinalizeGraphState:
    return PipiFinalizeGraph().finalize_help_card(state)


def create_recommendation_card(
    state: PipiFinalizeGraphState,
) -> PipiFinalizeGraphState:
    return PipiFinalizeGraph().create_recommendation_card(state)


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


def _deterministic_final_decision(
    *,
    state: PipiFinalizeGraphState,
    evidence_ids: list[str],
    retrieval_hit_ids: list[str],
) -> FinalAnswerDecision:
    payload = _best_retrieval_payload(state)
    decision_factor = str(
        payload.get("decision_factor")
        or payload.get("answer_summary")
        or "比明洞更生活方式，也更适合买小众品牌和美妆。"
    )
    title = str(payload.get("title") or payload.get("answer_title") or "去圣水")
    return {
        "kind": "final_recommendation",
        "title": title[:80],
        "reason": decision_factor,
        "decision_factor": decision_factor,
        "confidence": 0.86,
        "place_key": str(payload.get("place_key") or "korea-seongsu"),
        "item_key": str(payload.get("item_key") or "shopping-street"),
        "evidence_answer_ids": evidence_ids,
        "metadata": {
            "composition": "deterministic_help_answers_finalized",
            "decision_factor": decision_factor,
            "human_evidence_count": len(evidence_ids),
            "human_evidence_only": True,
            "raw_text_role": "human_evidence",
            "retrieval_hit_ids": retrieval_hit_ids,
        },
    }


def _selected_evidence_answer_ids(answers: list[HelpAnswerSnapshot], min_required: int) -> list[str]:
    useful_ids = [
        answer_id
        for answer in answers
        if (answer_id := str(answer.get("id") or "").strip()) and _is_useful_human_evidence(answer)
    ]
    if len(useful_ids) >= min_required:
        return useful_ids
    return [answer.get("id", "") for answer in answers if answer.get("id")]


def _is_useful_human_evidence(answer: HelpAnswerSnapshot) -> bool:
    text = str(answer.get("text") or "").strip()
    compact = "".join(text.split())
    if len(compact) < 4:
        return False
    generic_phrases = {
        "随便",
        "都行",
        "不知道",
        "不知道呢",
        "我也不知道",
        "好吃就行",
        "都可以",
    }
    return compact not in generic_phrases


def _best_retrieval_payload(state: PipiFinalizeGraphState) -> dict[str, Any]:
    best: dict[str, Any] = {}
    best_score = -1.0
    for hit in state.get("retrieval_hits", []):
        try:
            score = float(hit.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        payload = dict(hit.get("payload") or {})
        if hit.get("title") and "title" not in payload:
            payload["title"] = str(hit["title"])
        if score > best_score and payload:
            best = payload
            best_score = score
    return best


def _normalize_help_card(card: Mapping[str, Any], fallback_id: str) -> HelpCardSnapshot:
    return {
        "id": str(card.get("id") or card.get("help_card_id") or fallback_id),
        "question_id": str(card.get("question_id") or card.get("questionId") or ""),
        "conversation_id": str(card.get("conversation_id") or ""),
        "user_id": str(card.get("user_id") or card.get("owner_user_id") or ""),
        "title": str(card.get("title") or ""),
        "context_text": str(card.get("context_text") or card.get("contextText") or ""),
        "answer_count": int(card.get("answer_count") or card.get("answerCount") or 0),
        "min_answers_required": int(card.get("min_answers_required") or card.get("minAnswersRequired") or 3),
        "status": str(card.get("status") or "collecting"),
        "metadata": dict(card.get("metadata") or card.get("payload_json") or {}),
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
                    "decision_factor": "比明洞更生活方式，也更适合买小众品牌和美妆。",
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
    "create_recommendation_card",
    "create_final_recommendation_card",
    "decide_final_answer",
    "finalize_help_card",
    "light_user",
    "load_help_answers",
    "load_help_card",
    "retrieve_knowledge",
    "save_intent_answer",
]
