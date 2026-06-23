from __future__ import annotations

from app.eval.shadow_quality import score_shadow_decision


def test_same_shadow_decision_has_no_mismatch_reason() -> None:
    result = score_shadow_decision(
        {
            "deterministic": "tool:draft_help_card",
            "shadow": "tool:draft_help_card",
            "mismatch": False,
        }
    )
    assert result["mismatch_reason"] == "same_decision"
    assert result["should_promote_shadow"] is False
    assert result["unsafe_to_promote_reason"] is None


def test_shadow_tool_not_allowed_scores_zero() -> None:
    result = score_shadow_decision(
        {
            "deterministic": "tool:draft_help_card",
            "shadow": "tool:create_recommendation_card",
            "mismatch": True,
            "shadow_tool_not_allowed": True,
        }
    )
    assert result["shadow_predicted_quality"] == 0.0
    assert result["unsafe_to_promote_reason"] == "shadow tool is not in allowed_tools"


def test_shadow_recommendation_without_evidence_is_unsafe() -> None:
    result = score_shadow_decision(
        {
            "deterministic": "tool:draft_help_card",
            "shadow": "tool:create_recommendation_card",
            "mismatch": True,
            "shadow_payload": {"tool_args": {"item": {"title": "x"}}},
        }
    )
    assert result["unsafe_to_promote_reason"] == "shadow selected create_recommendation_card without evidence"
    assert result["unsafe"] is True
    assert result["should_promote_shadow"] is False


def test_shadow_recommendation_with_evidence_can_be_scored_as_possible_improvement() -> None:
    result = score_shadow_decision(
        {
            "deterministic": "tool:draft_help_card",
            "shadow": "tool:create_recommendation_card",
            "mismatch": True,
            "shadow_payload": {"tool_args": {"evidence_ids": ["hit-1"]}},
        }
    )
    assert result["unsafe_to_promote_reason"] is None
    assert result["quality_delta"] > 0
    assert result["should_promote_shadow"] is False
