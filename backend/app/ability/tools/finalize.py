from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.ability.schemas import (
    AbilityContext,
    AbilityTool,
    FinalizeHelpCardInput,
    FinalizeHelpCardOutput,
)
from app.ability.tools._common import maybe_override, metadata_int


async def run_finalize_help_card(
    context: AbilityContext,
    input_data: FinalizeHelpCardInput,
) -> FinalizeHelpCardOutput:
    handled, output = await maybe_override(context, "finalize_help_card", input_data)
    if handled:
        return output

    min_required = metadata_int(context, "min_answers_required", 0)
    answer_count = metadata_int(context, "answer_count", len(input_data.evidence_answer_ids))
    status = "finalize_accepted"
    if min_required and max(answer_count, len(input_data.evidence_answer_ids)) < min_required:
        status = "needs_more_answers"

    return FinalizeHelpCardOutput(
        help_card_id=input_data.help_card_id,
        question_id=input_data.question_id,
        conversation_id=input_data.conversation_id,
        user_id=input_data.user_id,
        status=status,
        evidence_answer_ids=input_data.evidence_answer_ids,
        confidence=input_data.confidence,
        source=input_data.source,
    )


def adapt_finalize_help_card_input(
    payload: Mapping[str, Any],
    context: AbilityContext,
) -> Mapping[str, Any]:
    normalized = dict(payload)
    normalized.pop("user_turn_id", None)
    if "help_card_id" not in normalized and "help_request_id" in normalized:
        normalized["help_card_id"] = normalized.pop("help_request_id")
    if not normalized.get("help_card_id") and context.metadata.get("help_card_id"):
        normalized["help_card_id"] = context.metadata["help_card_id"]
    if not normalized.get("question_id") and context.metadata.get("question_id"):
        normalized["question_id"] = context.metadata["question_id"]
    if not normalized.get("conversation_id") and context.metadata.get("conversation_id"):
        normalized["conversation_id"] = context.metadata["conversation_id"]
    if not normalized.get("user_id") and context.metadata.get("user_id"):
        normalized["user_id"] = context.metadata["user_id"]
    if "evidence_answer_ids" not in normalized:
        help_answers = context.metadata.get("help_answers") or []
        if isinstance(help_answers, list):
            normalized["evidence_answer_ids"] = [
                str(answer.get("id"))
                for answer in help_answers
                if isinstance(answer, dict) and answer.get("id")
            ]
    metadata = dict(normalized.get("metadata") or {})
    metadata.setdefault("source_type", "help_final")
    metadata.setdefault("source_ref_id", normalized.get("help_card_id"))
    metadata.setdefault("human_evidence_only", True)
    normalized["metadata"] = metadata
    return normalized


def build_finalize_help_card_tool() -> AbilityTool:
    return AbilityTool(
        name="finalize_help_card",
        input_schema=FinalizeHelpCardInput,
        output_schema=FinalizeHelpCardOutput,
        handler=run_finalize_help_card,
        input_adapter=adapt_finalize_help_card_input,
        description="Record the finalize orchestration boundary before final card side effects.",
    )


__all__ = [
    "adapt_finalize_help_card_input",
    "build_finalize_help_card_tool",
    "run_finalize_help_card",
]
