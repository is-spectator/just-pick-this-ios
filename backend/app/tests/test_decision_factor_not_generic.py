from __future__ import annotations

from app.harness.evaluator import evaluate_recommendation_card


def _base_card(decision_text: str) -> dict[str, object]:
    return {
        "item": {"title": "汉口热干面(朝阳店)"},
        "decision_factor": {"key": "stable_pick", "text": decision_text},
        "evidence_ids": ["retrieval-hit-1"],
        "image": None,
    }


def test_generic_decision_factor_is_rejected() -> None:
    result = evaluate_recommendation_card(_base_card("适合现在直接做决定。"))

    assert result.passed is False
    assert "decision_factor_too_weak" in result.errors


def test_decision_factor_must_be_more_than_stable_wording() -> None:
    result = evaluate_recommendation_card(_base_card("这一个证据最稳。"))

    assert result.passed is False
    assert "decision_factor_too_weak" in result.errors


def test_specific_area_food_route_decision_factor_passes() -> None:
    result = evaluate_recommendation_card(
        _base_card("朝阳区附近想吃热干面，先选这家，步行约 5 分钟。")
    )

    assert result.passed is True
    assert result.errors == []
