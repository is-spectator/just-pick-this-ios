from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from app.ability.schemas import AbilityContext, AbilityTool
from app.ability.tools._common import (
    maybe_override,
    metadata_int,
    metadata_mapping,
    stable_stub_id,
)
from app.schemas.tools import (
    DraftHelpCardInput,
    HelpCardOutput,
    PublishHelpCardInput,
    SubmitOneLinerAnswerInput,
    SubmitOneLinerAnswerOutput,
    UpdateHelpCardInput,
)


async def run_draft_help_card(
    context: AbilityContext,
    input_data: DraftHelpCardInput,
) -> HelpCardOutput:
    handled, output = await maybe_override(context, "draft_help_card", input_data)
    if handled:
        return output

    if context.db is not None:
        from app.tools.help_cards import draft_help_card

        return await draft_help_card(
            context.db,
            input_data,
            tool_call_logger=context.tool_call_logger,
            agent_run_id=context.agent_run_id,
        )

    return HelpCardOutput(
        help_card_id=stable_stub_id("help_card", input_data.question_id, input_data.title),
        question_id=input_data.question_id,
        owner_user_id=input_data.owner_user_id,
        title=input_data.title,
        context=input_data.context,
        wants=input_data.wants,
        avoids=input_data.avoids,
        constraints=input_data.constraints,
        revision=input_data.revision,
        reward=input_data.reward,
        answer_stats=input_data.answer_stats,
        status="draft",
        answer_count=0,
        min_answers_required=input_data.min_answers_required,
    )


async def run_update_help_card(
    context: AbilityContext,
    input_data: UpdateHelpCardInput,
) -> HelpCardOutput:
    handled, output = await maybe_override(context, "update_help_card", input_data)
    if handled:
        return output

    if context.db is not None:
        from app.tools.help_cards import update_help_card

        return await update_help_card(
            context.db,
            input_data,
            tool_call_logger=context.tool_call_logger,
            agent_run_id=context.agent_run_id,
        )

    current = _help_card_snapshot(context, input_data.help_card_id)
    return HelpCardOutput(
        help_card_id=input_data.help_card_id,
        question_id=str(current.get("question_id") or context.metadata.get("question_id") or ""),
        owner_user_id=str(
            input_data.owner_user_id
            or current.get("owner_user_id")
            or context.metadata.get("user_id")
            or ""
        ),
        title=input_data.title or str(current.get("title") or "求一个"),
        context=input_data.context or str(current.get("context") or current.get("context_text") or ""),
        wants=input_data.wants or list(current.get("wants") or []),
        avoids=input_data.avoids or list(current.get("avoids") or []),
        constraints=input_data.constraints or dict(current.get("constraints") or {}),
        revision=input_data.revision or int(current.get("revision") or 1),
        reward=input_data.reward or current.get("reward"),
        answer_stats=dict(current.get("answer_stats") or {}),
        status=str(current.get("status") or "draft"),
        answer_count=int(current.get("answer_count") or 0),
        min_answers_required=input_data.min_answers_required
        or int(current.get("min_answers_required") or 3),
        published_at=current.get("published_at"),
    )


async def run_publish_help_card(
    context: AbilityContext,
    input_data: PublishHelpCardInput,
) -> HelpCardOutput:
    handled, output = await maybe_override(context, "publish_help_card", input_data)
    if handled:
        return output

    if context.db is not None:
        from app.tools.help_cards import publish_help_card

        return await publish_help_card(
            context.db,
            input_data,
            tool_call_logger=context.tool_call_logger,
            agent_run_id=context.agent_run_id,
        )

    current = _help_card_snapshot(context, input_data.help_card_id)
    return HelpCardOutput(
        help_card_id=input_data.help_card_id,
        question_id=str(current.get("question_id") or context.metadata.get("question_id") or ""),
        owner_user_id=str(
            input_data.owner_user_id
            or current.get("owner_user_id")
            or context.metadata.get("user_id")
            or ""
        ),
        title=str(current.get("title") or "求一个"),
        context=str(current.get("context") or current.get("context_text") or ""),
        wants=list(current.get("wants") or []),
        avoids=list(current.get("avoids") or []),
        constraints=dict(current.get("constraints") or {}),
        revision=int(current.get("revision") or 1),
        reward=current.get("reward"),
        answer_stats=dict(current.get("answer_stats") or {}),
        status="published",
        answer_count=int(current.get("answer_count") or 0),
        min_answers_required=int(current.get("min_answers_required") or 3),
        published_at=datetime.now(timezone.utc),
    )


async def run_submit_one_liner_answer(
    context: AbilityContext,
    input_data: SubmitOneLinerAnswerInput,
) -> SubmitOneLinerAnswerOutput:
    handled, output = await maybe_override(context, "submit_one_liner_answer", input_data)
    if handled:
        return output

    if context.db is not None:
        from app.tools.help_cards import submit_one_liner_answer

        return await submit_one_liner_answer(
            context.db,
            input_data,
            tool_call_logger=context.tool_call_logger,
            agent_run_id=context.agent_run_id,
        )

    current_count = metadata_int(context, "answer_count", 0)
    min_required = metadata_int(context, "min_answers_required", 3)
    answer_count = current_count + 1
    return SubmitOneLinerAnswerOutput(
        help_answer_id=stable_stub_id(
            "help_answer",
            input_data.help_card_id,
            input_data.answer_user_id,
            input_data.raw_text,
        ),
        help_card_id=input_data.help_card_id,
        answer_user_id=input_data.answer_user_id,
        raw_text=input_data.raw_text,
        normalized_text=input_data.normalized_text or input_data.raw_text,
        status="submitted",
        reward_status="pending",
        answer_count=answer_count,
        finalization_ready=answer_count >= min_required,
    )


def adapt_draft_help_card_input(
    payload: Mapping[str, Any],
    context: AbilityContext,
) -> Mapping[str, Any]:
    normalized = dict(payload)
    question = normalized.pop("question", None)
    user_turn_id = normalized.pop("user_turn_id", None)
    normalized.pop("conversation_id", None)
    if question and not normalized.get("title"):
        normalized["title"] = str(question)[:120]
    if question and not normalized.get("context") and not normalized.get("context_text"):
        normalized["context"] = str(question)
    if not normalized.get("question_id"):
        normalized["question_id"] = context.metadata.get("question_id") or user_turn_id
    user_id = normalized.pop("user_id", None)
    if not normalized.get("owner_user_id"):
        normalized["owner_user_id"] = user_id or context.metadata.get("user_id")
    return normalized


def adapt_update_help_card_input(
    payload: Mapping[str, Any],
    context: AbilityContext,
) -> Mapping[str, Any]:
    normalized = dict(payload)
    normalized.pop("conversation_id", None)
    normalized.pop("user_turn_id", None)
    user_id = normalized.pop("user_id", None)
    if not normalized.get("owner_user_id"):
        normalized["owner_user_id"] = user_id or context.metadata.get("user_id")
    return normalized


def adapt_publish_help_card_input(
    payload: Mapping[str, Any],
    context: AbilityContext,
) -> Mapping[str, Any]:
    normalized = dict(payload)
    normalized.pop("conversation_id", None)
    normalized.pop("user_turn_id", None)
    user_id = normalized.pop("user_id", None)
    if not normalized.get("owner_user_id"):
        normalized["owner_user_id"] = user_id or context.metadata.get("user_id")
    return normalized


def adapt_submit_one_liner_answer_input(
    payload: Mapping[str, Any],
    context: AbilityContext,
) -> Mapping[str, Any]:
    normalized = dict(payload)
    normalized.pop("conversation_id", None)
    normalized.pop("user_turn_id", None)
    normalized.pop("evidence_type", None)
    user_id = normalized.pop("user_id", None)
    if "raw_text" not in normalized:
        normalized["raw_text"] = normalized.pop("content", None) or normalized.pop("text", None)
    if not normalized.get("answer_user_id"):
        normalized["answer_user_id"] = user_id or context.metadata.get("user_id")
    return normalized


def build_draft_help_card_tool() -> AbilityTool:
    return AbilityTool(
        name="draft_help_card",
        input_schema=DraftHelpCardInput,
        output_schema=HelpCardOutput,
        handler=run_draft_help_card,
        input_adapter=adapt_draft_help_card_input,
        description="Draft a help card when card evidence/image guardrails are not satisfied.",
    )


def build_update_help_card_tool() -> AbilityTool:
    return AbilityTool(
        name="update_help_card",
        input_schema=UpdateHelpCardInput,
        output_schema=HelpCardOutput,
        handler=run_update_help_card,
        input_adapter=adapt_update_help_card_input,
        description="Update an existing draft help card.",
    )


def build_publish_help_card_tool() -> AbilityTool:
    return AbilityTool(
        name="publish_help_card",
        input_schema=PublishHelpCardInput,
        output_schema=HelpCardOutput,
        handler=run_publish_help_card,
        input_adapter=adapt_publish_help_card_input,
        description="Publish a drafted help card.",
    )


def build_submit_one_liner_answer_tool() -> AbilityTool:
    return AbilityTool(
        name="submit_one_liner_answer",
        input_schema=SubmitOneLinerAnswerInput,
        output_schema=SubmitOneLinerAnswerOutput,
        handler=run_submit_one_liner_answer,
        input_adapter=adapt_submit_one_liner_answer_input,
        description="Persist a human one-liner as evidence, not as a final answer.",
    )


def _help_card_snapshot(context: AbilityContext, help_card_id: str) -> dict[str, Any]:
    help_card = context.metadata.get("help_card")
    if isinstance(help_card, dict) and _help_card_id_matches(help_card, help_card_id):
        return dict(help_card)
    help_cards = metadata_mapping(context, "help_cards")
    candidate = help_cards.get(help_card_id)
    return dict(candidate) if isinstance(candidate, dict) else {}


def _help_card_id_matches(help_card: Mapping[str, Any], help_card_id: str) -> bool:
    current_id = help_card.get("help_card_id") or help_card.get("id") or help_card.get("help_request_id")
    return current_id is None or str(current_id) == help_card_id


__all__ = [
    "adapt_draft_help_card_input",
    "adapt_publish_help_card_input",
    "adapt_submit_one_liner_answer_input",
    "adapt_update_help_card_input",
    "build_draft_help_card_tool",
    "build_publish_help_card_tool",
    "build_submit_one_liner_answer_tool",
    "build_update_help_card_tool",
    "run_draft_help_card",
    "run_publish_help_card",
    "run_submit_one_liner_answer",
    "run_update_help_card",
]
