from __future__ import annotations

from app.agent.pipi_loop import PipiState
from app.agent.schemas import AnswerDecision
from app.harness.answer_gate import AnswerGate


def test_greeting_answer_cannot_emit_ui_events() -> None:
    result = AnswerGate().validate(
        {"intent": "greeting"},
        AnswerDecision(message="你好", ui_events=[{"type": "show_help_card_draft", "help_card_id": "h"}]),
    )

    assert result.passed is False
    assert "non_task_answer_has_ui_events" in result.issues


def test_card_answer_must_come_from_tool_result() -> None:
    state = PipiState(conversation_id="c", turn_id="t", user_message="x")

    result = AnswerGate().validate(
        state,
        AnswerDecision(
            message="就这个",
            ui_events=[{"type": "show_recommendation_card", "card_id": "card"}],
            data={"recommendation_card": {"id": "card"}},
        ),
    )

    assert result.passed is False
    assert "recommendation_card_not_from_tool" in result.issues


def test_card_answer_from_tool_result_is_allowed() -> None:
    state = PipiState(
        conversation_id="c",
        turn_id="t",
        user_message="我在大同喜晋道，吃什么",
        tool_results=[
            {
                "decision": {"tool_name": "create_recommendation_card"},
                "tool_result": {
                    "tool_name": "create_recommendation_card",
                    "data": {"card_id": "card", "item": {"title": "刀削面 + 肉丸子"}},
                },
            }
        ],
    )

    result = AnswerGate().validate(
        state,
        AnswerDecision(
            message="别查了，就这个。",
            ui_events=[{"type": "show_recommendation_card", "card_id": "card"}],
            data={"recommendation_card": {"card_id": "card", "item": {"title": "刀削面 + 肉丸子"}}},
        ),
    )

    assert result.passed is True
    assert result.issues == []
