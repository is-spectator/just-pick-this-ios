from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.ability.schemas import AbilityContext, AbilityTool
from app.ability.tools._common import maybe_override, stable_stub_id
from app.schemas.tools import SaveIntentAnswerInput, SaveIntentAnswerOutput
from app.services.intent_answer_service import build_help_final_metadata


async def run_save_intent_answer(
    context: AbilityContext,
    input_data: SaveIntentAnswerInput,
) -> SaveIntentAnswerOutput:
    handled, output = await maybe_override(context, "save_intent_answer", input_data)
    if handled:
        return output

    if context.db is not None:
        from app.tools.intent_answers import save_intent_answer

        return await save_intent_answer(
            context.db,
            input_data,
            tool_call_logger=context.tool_call_logger,
            agent_run_id=context.agent_run_id,
        )

    intent_id = input_data.intent_id or stable_stub_id("intent", input_data.intent_key)
    return SaveIntentAnswerOutput(
        intent_answer_id=stable_stub_id(
            "intent_answer",
            input_data.help_card_id,
            input_data.question_id,
            input_data.answer_text,
        ),
        intent_id=intent_id,
        help_card_id=input_data.help_card_id,
        question_id=input_data.question_id,
        answer_text=input_data.answer_text,
        status="persisted",
        evidence_answer_ids=input_data.evidence_answer_ids,
    )


def adapt_save_intent_answer_input(
    payload: Mapping[str, Any],
    context: AbilityContext,
) -> Mapping[str, Any]:
    normalized = dict(payload)
    normalized.pop("user_turn_id", None)
    metadata = dict(normalized.get("metadata") or {})
    for key in (
        "recommendation_card_id",
        "decision_factor",
        "source_type",
        "source_ref_id",
        "confidence",
        "retrieval_hit_ids",
        "answer_title",
        "answer_summary",
    ):
        value = normalized.pop(key, None)
        if value is not None:
            metadata[key] = value
    if not normalized.get("question_id") and context.metadata.get("question_id"):
        normalized["question_id"] = context.metadata["question_id"]
    if not normalized.get("conversation_id") and context.metadata.get("conversation_id"):
        normalized["conversation_id"] = context.metadata["conversation_id"]
    help_card_id = normalized.get("help_card_id") or context.metadata.get("help_card_id")
    if help_card_id and _looks_like_help_final(metadata):
        metadata = build_help_final_metadata(
            help_card_id=str(help_card_id),
            recommendation_card_id=metadata.get("recommendation_card_id"),
            evidence_answer_ids=list(normalized.get("evidence_answer_ids") or []),
            decision_factor=metadata.get("decision_factor"),
            confidence=metadata.get("confidence"),
            retrieval_hit_ids=list(metadata.get("retrieval_hit_ids") or []),
            base=metadata,
        )
    if metadata:
        normalized["metadata"] = metadata
    return normalized


def _looks_like_help_final(metadata: Mapping[str, Any]) -> bool:
    return bool(
        metadata.get("source_type") == "help_final"
        or metadata.get("source_ref_id")
        or metadata.get("recommendation_card_id")
        or metadata.get("decision_factor")
    )


def build_save_intent_answer_tool() -> AbilityTool:
    return AbilityTool(
        name="save_intent_answer",
        input_schema=SaveIntentAnswerInput,
        output_schema=SaveIntentAnswerOutput,
        handler=run_save_intent_answer,
        input_adapter=adapt_save_intent_answer_input,
        description="Persist a finalized answer as reusable intent evidence.",
    )


__all__ = [
    "adapt_save_intent_answer_input",
    "build_save_intent_answer_tool",
    "run_save_intent_answer",
]
