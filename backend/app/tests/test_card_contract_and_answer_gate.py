from __future__ import annotations

from app.agent.schemas import AnswerDecision
from app.harness.answer_gate import AnswerGate
from app.harness.evaluator import Evaluator
from app.schemas.cards import CardSummary


def test_evaluator_requires_item_title_single_decision_factor_and_evidence_ids() -> None:
    result = Evaluator().evaluate_recommendation_card(
        {
            "title": "三里屯川菜馆",
            "decision_factors": [{"text": "近"}, {"text": "稳"}],
            "decision_factor": [{"text": "近"}, {"text": "稳"}],
            "provenance": {"evidence_ids": ["hit-1"]},
            "reasons": [],
            "bullets": [],
            "followups": [],
        }
    )

    issues = set(result.issues)
    assert result.passed is False
    assert "recommendation_card_missing_item_title" in issues
    assert "recommendation_card_must_use_singular_decision_factor" in issues
    assert "recommendation_card_decision_factor_must_be_single" in issues
    assert "recommendation_card_missing_evidence_ids" in issues
    assert "recommendation_card_forbidden_reasons" in issues
    assert "recommendation_card_forbidden_bullets" in issues
    assert "recommendation_card_forbidden_followups" in issues


def test_evaluator_accepts_minimal_recommendation_card_contract() -> None:
    result = Evaluator().evaluate_recommendation_card(
        {
            "item": {"title": "海底捞番茄锅 + 菌汤锅"},
            "decision_factor": {"key": "not_spicy", "text": "不吃辣时，番茄锅和菌汤锅最稳。"},
            "evidence_ids": ["menu-hit-1"],
            "image": {"id": "img-1", "verified": True, "is_ai_generated": False},
        }
    )

    assert result.passed is True
    assert result.issues == []


def test_evaluator_downscores_generic_help_card_fields() -> None:
    result = Evaluator().evaluate_help_card(
        {
            "title": "求一个",
            "context": {"city": "北京"},
            "wants": ["靠谱"],
            "avoids": ["踩雷"],
        }
    )

    issues = set(result.issues)
    assert result.passed is False
    assert "help_card_title_too_generic" in issues
    assert "help_card_context_too_generic" in issues
    assert "help_card_wants_too_generic" in issues
    assert "help_card_avoids_too_generic" in issues


def test_evaluator_haidilao_sanlitun_rejects_area_restaurant_route() -> None:
    result = Evaluator().evaluate_response(
        "我在海底捞三里屯店，两个人不吃辣帮我点什么",
        {
            "location_state": "in_area",
            "data": {
                "recommendation_card": {
                    "title": "三里屯川菜馆候选",
                    "location_state": "in_area",
                    "target_type": "restaurant",
                    "item": {"title": "三里屯川菜馆候选"},
                    "decision_factor": {"text": "附近餐厅看起来不错。"},
                    "evidence_ids": ["area-hit-1"],
                }
            },
            "ui_events": [{"type": "show_recommendation_card", "card_id": "card-area"}],
        },
    )

    issues = set(result.issues)
    assert result.passed is False
    assert "venue_order_should_route_in_venue" in issues
    assert "venue_order_should_return_ordering_bundle" in issues
    assert "haidilao_route_overridden_by_area_restaurant" in issues


def test_answer_gate_blocks_greeting_ui_events_and_ui_copy() -> None:
    result = AnswerGate().validate(
        {"intent": "greeting"},
        AnswerDecision(
            message="我给你展示一张推荐卡。",
            ui_events=[
                {
                    "type": "show_recommendation_card",
                    "card_id": "card-1",
                    "title": "推荐卡",
                }
            ],
        ),
    )

    issues = set(result.issues)
    assert result.passed is False
    assert "non_task_answer_has_ui_events" in issues
    assert "answer_contains_forbidden_ui_copy" in issues
    assert "ui_event_contains_forbidden_copy" in issues
    assert "ui_event_card_id_not_persisted" in issues
    assert "ui_event_card_id_not_from_tool" in issues


def test_answer_gate_blocks_internal_runtime_copy() -> None:
    result = AnswerGate().validate(
        AnswerDecision(
            message="抱歉，目前没有可用的工具进行搜索，请换个方式。",
            ui_events=[],
            data={},
        )
    )

    assert result.passed is False
    assert "answer_contains_forbidden_ui_copy" in result.issues


def test_answer_gate_blocks_unpersisted_help_card_ui_event() -> None:
    result = AnswerGate().validate(
        AnswerDecision(
            message="这题先求一个。",
            ui_events=[{"type": "show_help_card_draft", "help_card_id": "help-1"}],
            data={"help_card": {"help_card_id": "help-1", "title": "三里屯川菜求一个"}},
        )
    )

    issues = set(result.issues)
    assert result.passed is False
    assert "help_card_not_from_tool" in issues
    assert "ui_event_help_card_id_not_persisted" in issues
    assert "ui_event_help_card_id_not_from_tool" in issues


def test_answer_gate_blocks_card_json_that_did_not_come_from_tool() -> None:
    result = AnswerGate().validate(
        '{"id":"card-1","item":{"title":"刀削面"},"decision_factor":{"text":"地方记忆点强"},"evidence_ids":["hit-1"]}'
    )

    assert result.passed is False
    assert any(issue.startswith("answer_contains_unpersisted_card_json") for issue in result.issues)
    assert any(issue.startswith("answer_contains_card_json_not_from_tool") for issue in result.issues)


def test_answer_gate_allows_tool_backed_card_id() -> None:
    state = {
        "tool_results": [
            {
                "decision": {"tool_name": "create_recommendation_card"},
                "tool_result": {
                    "tool_name": "create_recommendation_card",
                    "data": {"card_id": "card-1"},
                },
            }
        ]
    }

    result = AnswerGate().validate(
        state,
        AnswerDecision(
            message="别查了，就这个。",
            ui_events=[{"type": "show_recommendation_card", "card_id": "card-1"}],
            data={
                "recommendation_card": {
                    "card_id": "card-1",
                    "item": {"title": "刀削面"},
                    "decision_factor": {"text": "地方记忆点强"},
                    "evidence_ids": ["hit-1"],
                }
            },
        ),
    )

    assert result.passed is True
    assert result.issues == []


def test_card_summary_strips_legacy_card_copy_fields() -> None:
    card = CardSummary.model_validate(
        {
            "id": "card-1",
            "type": "recommendation_card",
            "title": "刀削面",
            "decision_factor": "地方记忆点强",
            "provenance": {"evidence_ids": ["hit-1"]},
            "reasons": ["旧原因"],
            "bullets": ["旧 bullet"],
            "followups": ["旧 followup"],
        }
    )

    dumped = card.model_dump()
    assert dumped["item"] == {"title": "刀削面"}
    assert dumped["decision_factor"] == {"text": "地方记忆点强"}
    assert dumped["evidence_ids"] == ["hit-1"]
    assert "reasons" not in dumped
    assert "bullets" not in dumped
    assert "followups" not in dumped
