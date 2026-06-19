from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


HELP_FINAL_SOURCE_TYPE = "help_final"


def build_help_final_metadata(
    *,
    help_card_id: str,
    recommendation_card_id: str | None = None,
    evidence_answer_ids: Sequence[str] | None = None,
    decision_factor: str | None = None,
    confidence: Any = None,
    retrieval_hit_ids: Sequence[str] | None = None,
    base: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build canonical provenance for IntentAnswer rows created by FinalizeGraph."""

    metadata = dict(base or {})
    metadata["source_type"] = HELP_FINAL_SOURCE_TYPE
    metadata["source_ref_id"] = str(help_card_id)
    metadata["help_card_id"] = str(help_card_id)
    metadata["human_evidence_only"] = True
    metadata["raw_text_role"] = "human_evidence"
    if recommendation_card_id:
        metadata["recommendation_card_id"] = str(recommendation_card_id)
    if evidence_answer_ids is not None:
        metadata["evidence_answer_ids"] = [str(item) for item in evidence_answer_ids]
    if decision_factor:
        metadata["decision_factor"] = str(decision_factor)
    parsed_confidence = confidence_value(confidence)
    if parsed_confidence is not None:
        metadata["confidence"] = parsed_confidence
    if retrieval_hit_ids is not None:
        metadata["retrieval_hit_ids"] = [str(item) for item in retrieval_hit_ids]
    return metadata


def confidence_value(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(parsed, 1.0))


__all__ = ["HELP_FINAL_SOURCE_TYPE", "build_help_final_metadata", "confidence_value"]
