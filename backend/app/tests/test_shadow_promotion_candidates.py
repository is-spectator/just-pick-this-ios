from __future__ import annotations

from app.eval.shadow_promotion_generator import generate_shadow_promotion_candidates


def test_shadow_promotion_candidates_are_review_only() -> None:
    candidates = generate_shadow_promotion_candidates(
        {
            "decisions": [
                {
                    "case_id": "better-shadow",
                    "group": "area_food",
                    "deterministic": "tool:draft_help_card",
                    "shadow": "tool:create_recommendation_card",
                    "mismatch": True,
                    "quality_delta": 0.18,
                    "schema_valid": True,
                    "trace_id": "trace-1",
                }
            ]
        }
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["candidate_type"] == "possible_improvement"
    assert candidate["priority"] == "P1"
    assert candidate["autopromote"] is False
    assert candidate["review_required"] is True
    assert "review_seed_gap" in candidate["suggested_actions"]


def test_shadow_promotion_candidates_keep_runtime_errors_separate() -> None:
    candidates = generate_shadow_promotion_candidates(
        {
            "decisions": [
                {
                    "case_id": "schema-error",
                    "group": "venue_order",
                    "schema_error": True,
                    "schema_valid": False,
                },
                {
                    "case_id": "provider-error",
                    "group": "smalltalk",
                    "provider_error": True,
                    "schema_valid": False,
                },
                {
                    "case_id": "timeout",
                    "group": "shopping",
                    "timeout": True,
                    "schema_valid": False,
                },
            ]
        }
    )

    by_case = {candidate["case_id"]: candidate for candidate in candidates}
    assert by_case["schema-error"]["candidate_type"] == "shadow_runtime_reliability"
    assert by_case["schema-error"]["priority"] == "P1"
    assert "fix_shadow_schema_prompt" in by_case["schema-error"]["suggested_actions"]
    assert by_case["provider-error"]["candidate_type"] == "shadow_runtime_reliability"
    assert "inspect_provider_reliability" in by_case["provider-error"]["suggested_actions"]
    assert by_case["timeout"]["candidate_type"] == "shadow_runtime_reliability"
    assert "keep_product_deterministic" in by_case["timeout"]["suggested_actions"]


def test_shadow_promotion_candidates_filter_non_actionable_matches() -> None:
    candidates = generate_shadow_promotion_candidates(
        {
            "decisions": [
                {
                    "case_id": "same",
                    "group": "area_food",
                    "deterministic": "tool:create_recommendation_card",
                    "shadow": "tool:create_recommendation_card",
                    "mismatch": False,
                    "schema_valid": True,
                },
                {
                    "case_id": "unsafe",
                    "group": "area_food",
                    "deterministic": "tool:draft_help_card",
                    "shadow": "tool:create_recommendation_card",
                    "mismatch": True,
                    "unsafe": True,
                    "unsafe_to_promote_reason": "missing_evidence",
                    "schema_valid": True,
                },
            ]
        }
    )

    assert [candidate["case_id"] for candidate in candidates] == ["unsafe"]
    assert candidates[0]["candidate_type"] == "unsafe_shadow_review"
    assert candidates[0]["priority"] == "P1"
    assert "keep_shadow_blocked" in candidates[0]["suggested_actions"]
