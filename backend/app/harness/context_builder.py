from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.retrieval.evidence_pack import build_evidence_pack, summarize_evidence_pack


class PipiContextPack(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True, str_strip_whitespace=True)

    conversation_id: str | None = None
    user_turn_id: str | None = None
    user_message: str
    input_gate_result: dict[str, Any] | None = None
    intent_type: str | None = None
    should_enter_loop: bool | None = None
    should_create_question: bool | None = None
    should_retrieve: bool | None = None
    conversation_summary: str | None = None
    active_help_card: dict[str, Any] | None = None
    active_question: dict[str, Any] | None = None
    recent_turns: list[dict[str, Any]] = Field(default_factory=list, max_length=3)
    retrieval_summary: dict[str, Any] | None = None
    evidence_pack: dict[str, Any] | None = None
    strongest_evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=5)
    allowed_tools: list[str] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)
    client_context: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_context_snapshot(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "user_turn_id": self.user_turn_id,
            "user_message": self.user_message,
            "input_gate_result": dict(self.input_gate_result or {}),
            "intent_type": self.intent_type,
            "recent_turns": list(self.recent_turns),
            "evidence_pack": summarize_evidence_pack(self.evidence_pack),
            "facts": dict(self.facts),
        }


class ContextBuilder:
    """Builds a small context pack for the reasoner."""

    def build(
        self,
        gate_result: Any | None = None,
        *,
        conversation_id: str | None = None,
        user_turn_id: str | None = None,
        user_message: str | None = None,
        allowed_tools: list[str] | None = None,
        recent_turns: list[dict[str, Any]] | None = None,
        active_help_card: dict[str, Any] | None = None,
        active_question: dict[str, Any] | None = None,
        retrieval_summary: dict[str, Any] | None = None,
        evidence_pack: dict[str, Any] | None = None,
        strongest_evidence: list[dict[str, Any]] | None = None,
        conversation_summary: str | None = None,
        facts: dict[str, Any] | None = None,
        client_context: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PipiContextPack:
        gate_data = _dump(gate_result)
        resolved_user_message = str(
            user_message
            or gate_data.get("user_message")
            or gate_data.get("message")
            or ""
        ).strip()
        resolved_allowed_tools = allowed_tools
        if resolved_allowed_tools is None:
            resolved_allowed_tools = list(gate_data.get("allowed_tools") or [])
        source_recent_turns = (
            recent_turns if recent_turns is not None else list(gate_data.get("recent_turns") or [])
        )
        merged_facts = _derive_facts(
            user_message=resolved_user_message,
            recent_turns=source_recent_turns,
            facts={**dict(gate_data.get("facts") or {}), **dict(facts or {})},
        )
        strongest = _strongest_evidence(strongest_evidence or [])
        resolved_evidence_pack = evidence_pack
        if resolved_evidence_pack is None and strongest:
            resolved_evidence_pack = build_evidence_pack(
                strongest,
                retrieval_run=retrieval_summary,
            )
        resolved_retrieval_summary = dict(retrieval_summary or {})
        if resolved_evidence_pack is not None:
            resolved_retrieval_summary.setdefault(
                "evidence_pack",
                summarize_evidence_pack(resolved_evidence_pack),
            )
        return PipiContextPack(
            conversation_id=conversation_id or gate_data.get("conversation_id"),
            user_turn_id=user_turn_id or gate_data.get("user_turn_id") or gate_data.get("turn_id"),
            user_message=resolved_user_message,
            input_gate_result=gate_data or None,
            intent_type=_optional_str(gate_data.get("intent_type") or gate_data.get("intent")),
            should_enter_loop=_optional_bool(gate_data.get("should_enter_loop")),
            should_create_question=_optional_bool(gate_data.get("should_create_question")),
            should_retrieve=_optional_bool(gate_data.get("should_retrieve")),
            conversation_summary=conversation_summary,
            active_help_card=active_help_card,
            active_question=active_question,
            recent_turns=_recent_turns(source_recent_turns),
            retrieval_summary=resolved_retrieval_summary or None,
            evidence_pack=resolved_evidence_pack,
            strongest_evidence=strongest,
            allowed_tools=list(dict.fromkeys(resolved_allowed_tools)),
            facts=merged_facts,
            client_context={
                **dict(gate_data.get("client_context") or {}),
                **dict(client_context or {}),
            },
            metadata={**dict(gate_data.get("metadata") or {}), **dict(metadata or {})},
        )

    def from_graph_state(
        self,
        state: dict[str, Any],
        *,
        allowed_tools: list[str],
        active_help_card: dict[str, Any] | None = None,
        active_question: dict[str, Any] | None = None,
    ) -> PipiContextPack:
        context = dict(state.get("context") or {})
        retrieval = dict(state.get("retrieval_run") or {})
        hits = list(state.get("retrieval_hits") or [])
        evidence_pack = build_evidence_pack(hits, retrieval_run=retrieval) if hits else None
        return self.build(
            user_message=str(state.get("user_message") or ""),
            allowed_tools=allowed_tools,
            recent_turns=list(context.get("recent_turns") or []),
            active_help_card=active_help_card,
            active_question=active_question,
            facts=dict(context.get("facts") or {}),
            retrieval_summary={
                "id": retrieval.get("id"),
                "query": retrieval.get("query"),
                "hit_count": len(hits),
            }
            if retrieval
            else None,
            evidence_pack=evidence_pack,
            strongest_evidence=_strongest_evidence(hits),
        )


PipiContextBuilder = ContextBuilder


def build_context_pack(
    gate_result: Any | None = None,
    **kwargs: Any,
) -> PipiContextPack:
    return ContextBuilder().build(gate_result, **kwargs)


def _dump(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return dict(value)
    return {}


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _derive_facts(
    *,
    user_message: str,
    recent_turns: list[dict[str, Any]],
    facts: dict[str, Any],
) -> dict[str, Any]:
    previous_user_messages = [
        str(turn.get("content") or "")
        for turn in recent_turns
        if isinstance(turn, dict) and turn.get("role", "user") == "user"
    ]
    latest_context = facts.get("latest_user_context") or _latest_user_context(
        previous_user_messages
    )
    current_is_followup = _is_contextual_followup(user_message)
    resolved = facts.get("resolved_user_message")
    if not resolved:
        resolved = (
            f"{latest_context}; follow-up: {user_message}"
            if latest_context and current_is_followup
            else user_message
        )
    return {
        **facts,
        "latest_user_context": latest_context,
        "resolved_user_message": resolved,
        "has_decision_context": bool(latest_context),
        "current_is_contextual_followup": current_is_followup,
    }


def _recent_turns(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(turn) for turn in list(turns)[-3:] if isinstance(turn, dict)]


def _strongest_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [dict(item) for item in evidence if isinstance(item, dict)],
        key=lambda item: float(item.get("score") or 0),
        reverse=True,
    )[:5]


def _latest_user_context(messages: list[str]) -> str | None:
    hints = ("推荐", "选", "吃", "逛", "买", "喝", "玩", "附近", "我在", "现在在", "想找")
    for message in reversed(messages):
        text = message.strip()
        if text and any(hint in text for hint in hints):
            return text
    for message in reversed(messages):
        text = message.strip()
        if text:
            return text
    return None


def _is_contextual_followup(message: str) -> bool:
    normalized = message.strip().lower()
    if normalized in {
        "吃",
        "吃的",
        "吃饭",
        "逛",
        "逛的",
        "买",
        "买的",
        "喝",
        "喝的",
        "附近",
        "都行",
    }:
        return True
    return 0 < len(normalized) <= 10 and any(
        hint in normalized for hint in ("吃", "逛", "买", "玩", "喝", "店")
    )


__all__ = [
    "ContextBuilder",
    "PipiContextBuilder",
    "PipiContextPack",
    "build_context_pack",
]
