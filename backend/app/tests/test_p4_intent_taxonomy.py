from __future__ import annotations

from typing import Any, get_args

from app.agent.model_adapter import get_deterministic_model_adapter
from app.agent.state import PipiChatGraphState, PipiIntent


DESIGN_INTENTS = {
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
}


def _state(
    message: str,
    *,
    intent: str,
    metadata: dict[str, Any] | None = None,
) -> PipiChatGraphState:
    return {
        "conversation_id": "conversation-taxonomy-test",
        "user_turn_id": "turn-taxonomy-test",
        "user_message": message,
        "agent_run_id": "agent-run-taxonomy-test",
        "intent": intent,  # type: ignore[typeddict-item]
        "metadata": metadata or {},
        "retrieval_hits": [],
    }


def test_intent_taxonomy_matches_design() -> None:
    assert set(get_args(PipiIntent)) == DESIGN_INTENTS


def test_korea_niche_can_route_to_help_request() -> None:
    adapter = get_deterministic_model_adapter()
    message = "在韩国逛街，不想去明洞，想小众，求一个。"

    intent = adapter.classify_intent(message)
    next_action, tool_call = adapter.decide_next_action(_state(message, intent=intent))

    assert intent == "help_request"
    assert next_action == "call_tool"
    assert tool_call is not None
    assert tool_call["name"] == "draft_help_card"


def test_budget_feedback_routes_to_update_help_card() -> None:
    adapter = get_deterministic_model_adapter()
    message = "预算不高，别太远，不要游客区，也想买美妆。"

    intent = adapter.classify_intent(message)
    next_action, tool_call = adapter.decide_next_action(
        _state(
            message,
            intent=intent,
            metadata={"active_help_card_id": "help-card-taxonomy-test"},
        )
    )

    assert intent == "update_help_card"
    assert next_action == "call_tool"
    assert tool_call is not None
    assert tool_call["name"] == "update_help_card"


def test_one_liner_routes_to_one_liner_answer_when_in_answer_context() -> None:
    adapter = get_deterministic_model_adapter()
    message = "来一句：去圣水，比明洞更适合买小众品牌。"

    intent = adapter.classify_intent(message)
    next_action, tool_call = adapter.decide_next_action(
        _state(
            message,
            intent=intent,
            metadata={
                "help_card_id": "help-card-taxonomy-test",
                "answer_context": True,
            },
        )
    )

    assert intent == "one_liner_answer"
    assert next_action == "call_tool"
    assert tool_call is not None
    assert tool_call["name"] == "submit_one_liner_answer"
