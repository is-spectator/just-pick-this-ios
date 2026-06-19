from __future__ import annotations

from app.schemas.tools import (
    CreateRecommendationCardInput,
    DraftHelpCardInput,
    HelpCardOutput,
    RecommendationCardItem,
    RecommendationDecisionFactor,
    UpdateHelpCardInput,
)


def _field_names(model: type) -> set[str]:
    return set(model.model_fields)


def test_recommendation_card_schema_is_minimal() -> None:
    item_fields = _field_names(RecommendationCardItem)
    decision_factor_fields = _field_names(RecommendationDecisionFactor)
    input_fields = _field_names(CreateRecommendationCardInput)

    assert {"title", "subtitle", "category"} <= item_fields
    assert {"text", "key"} <= decision_factor_fields
    assert {
        "item",
        "decision_factor",
        "image_asset_id",
        "evidence_ids",
        "retrieval_run_id",
    } <= input_fields

    legacy_display_fields = {
        "reasons",
        "reason",
        "bullets",
        "followups",
        "warning",
    }
    assert input_fields.isdisjoint(legacy_display_fields)


def test_help_card_schema_is_structured() -> None:
    required_structured_fields = {
        "context",
        "wants",
        "avoids",
        "constraints",
        "revision",
        "reward",
        "answer_stats",
    }

    draft_fields = _field_names(DraftHelpCardInput)
    output_fields = _field_names(HelpCardOutput)
    update_fields = _field_names(UpdateHelpCardInput)

    assert required_structured_fields <= draft_fields
    assert required_structured_fields <= output_fields
    assert {"context", "wants", "avoids", "constraints", "revision", "reward"} <= update_fields
    assert "context_text" not in draft_fields
    assert "context_text" not in output_fields
