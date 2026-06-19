from __future__ import annotations

from app.harness.evaluator import evaluate_help_card


def test_generic_help_card_is_rejected() -> None:
    result = evaluate_help_card(
        {
            "title": "北京这顿饭，求一个",
            "context": {"city": "北京"},
            "wants": ["好吃", "别让我查"],
            "avoids": ["多个选项"],
        }
    )

    assert result.passed is False
    assert "help_card_title_too_generic" in result.errors
    assert "help_card_context_too_generic" in result.errors
    assert "help_card_wants_too_generic" in result.errors
    assert "help_card_avoids_too_generic" in result.errors


def test_structured_unknown_area_food_help_card_passes_quality_gate() -> None:
    result = evaluate_help_card(
        {
            "title": "朝阳区热干面，求一个靠谱选择",
            "context": {
                "city": "北京",
                "area": "朝阳区",
                "wants": ["热干面"],
                "scene": "现在就吃",
            },
            "wants": ["热干面"],
            "avoids": ["太远"],
            "constraints": ["只要一个选择"],
        }
    )

    assert result.passed is True
    assert result.errors == []
