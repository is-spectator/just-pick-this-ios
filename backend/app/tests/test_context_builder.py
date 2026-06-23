from __future__ import annotations

from app.harness.context_builder import ContextBuilder
from app.harness.input_gate import run_input_gate


def test_context_builder_keeps_context_small() -> None:
    pack = ContextBuilder().build(
        user_message="我在三里屯想吃川菜",
        allowed_tools=["search_knowledge", "draft_help_card", "draft_help_card"],
        recent_turns=[{"id": str(index)} for index in range(6)],
        strongest_evidence=[{"score": score} for score in range(8)],
    )

    assert [turn["id"] for turn in pack.recent_turns] == ["3", "4", "5"]
    assert len(pack.strongest_evidence) == 5
    assert pack.allowed_tools == ["search_knowledge", "draft_help_card"]


def test_context_builder_preserves_input_gate_result_for_trace() -> None:
    gate = run_input_gate("我在大同喜晋道，吃什么")

    pack = ContextBuilder().build(
        gate,
        conversation_id="conversation-id",
        user_turn_id="turn-id",
        user_message="我在大同喜晋道，吃什么",
    )

    assert pack.conversation_id == "conversation-id"
    assert pack.user_turn_id == "turn-id"
    assert pack.input_gate_result is not None
    assert pack.input_gate_result["intent_type"] == "decision_request"
    assert pack.should_enter_loop is True
    assert pack.should_create_question is True
    assert pack.should_retrieve is True
