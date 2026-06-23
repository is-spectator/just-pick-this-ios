from __future__ import annotations

from app.agent.reasoner import _openai_reasoner_messages
from app.agent.schemas import AnswerDecision
from app.agent.shadow_reasoner import _openai_shadow_messages
from app.ops.prompt_service import (
    EVALUATOR_CURRENT_SYSTEM,
    HELP_CARD_EXTRACTOR_CURRENT_SYSTEM,
    REASONER_CURRENT_SYSTEM,
    SHADOW_REASONER_CURRENT_SYSTEM,
)


def test_reasoner_prompt_contains_hard_harness_rules() -> None:
    runtime_prompt = _openai_reasoner_messages(
        state={
            "user_message": "我在三里屯想吃川菜",
            "metadata": {
                "input_gate_result": {
                    "intent_type": "decision_request",
                    "confidence": 0.9,
                    "should_enter_loop": True,
                    "should_create_question": True,
                    "should_retrieve": True,
                    "allowed_tools": ["search_knowledge", "create_recommendation_card", "draft_help_card"],
                    "reason": "test",
                }
            },
        },
        baseline=AnswerDecision(message="baseline"),
    )[0]["content"]
    combined = runtime_prompt + "\n" + REASONER_CURRENT_SYSTEM

    assert "二选一" in combined
    assert "不能绕过 tool" in combined or "不能绕过 tool/function call" in combined
    assert "不能直接吐推荐卡 JSON" in combined
    assert "decision_request/help_request 首轮必须先 search_knowledge" in combined
    assert "证据不足" in combined and "draft_help_card" in combined
    assert "tool_result" in combined and "answer 收口" in combined
    assert "greeting" in combined and "不能调用工具" in combined


def test_shadow_prompt_is_audit_only_and_side_effect_free() -> None:
    runtime_prompt = _openai_shadow_messages(
        context_pack={"user_message": "你好"},
        deterministic_decision=AnswerDecision(message="你好"),
    )[0]["content"]
    combined = runtime_prompt + "\n" + SHADOW_REASONER_CURRENT_SYSTEM

    assert "audit-only" in combined
    assert "why_different_from_deterministic" in combined
    assert "risk_if_promoted" in combined
    assert "confidence" in combined
    assert "不能调用 AbilityCenter" in combined
    assert "不能写 RecommendationCard/HelpCard" in combined
    assert "不能改变 product output" in combined
    assert "调用 AbilityCenter 执行" not in combined
    assert "写入 RecommendationCard" not in combined


def test_help_card_extractor_prompt_describes_problem_compressor_contract() -> None:
    assert "问题压缩器" in HELP_CARD_EXTRACTOR_CURRENT_SYSTEM
    assert "title、context、wants、avoids、constraints、missing_info" in HELP_CARD_EXTRACTOR_CURRENT_SYSTEM
    assert "北京这顿饭，求一个" in HELP_CARD_EXTRACTOR_CURRENT_SYSTEM
    assert "好吃" in HELP_CARD_EXTRACTOR_CURRENT_SYSTEM
    assert "多个选项" in HELP_CARD_EXTRACTOR_CURRENT_SYSTEM


def test_evaluator_prompt_marks_image_optional_but_verified_when_present() -> None:
    assert "图片可选" in EVALUATOR_CURRENT_SYSTEM
    assert "无图时仍可推荐" in EVALUATOR_CURRENT_SYSTEM
    assert "verified/displayable" in EVALUATOR_CURRENT_SYSTEM
    assert "is_ai_generated=false" in EVALUATOR_CURRENT_SYSTEM
