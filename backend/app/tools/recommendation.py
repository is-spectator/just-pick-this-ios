from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from app.schemas.tools import CreateRecommendationCardInput, RecommendationCardOutput
from app.tools.errors import ToolValidationError
from app.tools.session import SessionLike, commit, execute, first_mapping, rollback
from app.tools.tool_call_logger import (
    ToolCallLogger,
    ensure_tool_call_logger,
    finish_tool_call,
    start_tool_call,
)


async def create_recommendation_card(
    db: SessionLike,
    input_data: CreateRecommendationCardInput | Mapping[str, Any],
    *,
    tool_call_logger: ToolCallLogger | None = None,
    agent_run_id: str | None = None,
) -> RecommendationCardOutput:
    input_data = _normalize_input(input_data)
    tool_call_logger = ensure_tool_call_logger(
        db,
        tool_call_logger,
        agent_run_id=agent_run_id,
    )
    tool_call_id = await start_tool_call(
        tool_call_logger,
        tool_name="create_recommendation_card",
        input_json=input_data.model_dump(mode="json"),
        agent_run_id=agent_run_id,
        question_id=input_data.question_id,
        help_request_id=input_data.help_card_id,
    )
    try:
        if not input_data.evidence_ids:
            raise ToolValidationError("Recommendation card requires evidence_ids.")
        if input_data.image_asset_id is not None:
            await _assert_displayable_non_ai_image_asset(db, input_data.image_asset_id)
        context = await _get_card_context(
            db,
            question_id=input_data.question_id,
            help_card_id=input_data.help_card_id,
        )
        user_id = input_data.user_id or context.get("user_id")
        if not user_id:
            raise ToolValidationError("User is required before creating a recommendation card.")
        image_status = "attached" if input_data.image_asset_id else "missing"
        image_required = bool(input_data.image_required and input_data.image_asset_id)
        decision_text = input_data.decision_factor.text
        payload = {
            "item": input_data.item.model_dump(mode="json"),
            "decision_factor": input_data.decision_factor.model_dump(mode="json"),
            "evidence_ids": input_data.evidence_ids,
            "retrieval_run_id": input_data.retrieval_run_id,
            "intent_answer_id": input_data.intent_answer_id,
            "source_help_card_id": input_data.help_card_id,
        }

        result = await execute(
            db,
            """
            INSERT INTO recommendation_cards (
                id,
                question_id,
                conversation_id,
                user_id,
                agent_run_id,
                tool_call_id,
                image_asset_id,
                image_required,
                image_status,
                source,
                title,
                subtitle,
                reason,
                bullets_json,
                warning,
                confidence,
                status,
                payload_json,
                created_at,
                updated_at
            )
            VALUES (
                :id,
                :question_id,
                :conversation_id,
                :user_id,
                :agent_run_id,
                :tool_call_id,
                :image_asset_id,
                :image_required,
                :image_status,
                :source,
                :title,
                :subtitle,
                :reason,
                CAST(:bullets AS JSONB),
                :warning,
                :confidence,
                :status,
                CAST(:payload_json AS JSONB),
                NOW(),
                NOW()
            )
            RETURNING id
            """,
            {
                "id": str(uuid4()),
                "question_id": context["question_id"],
                "conversation_id": context["conversation_id"],
                "user_id": user_id,
                "agent_run_id": agent_run_id,
                "tool_call_id": tool_call_id,
                "source": input_data.source,
                "title": input_data.item.title,
                "subtitle": input_data.item.subtitle,
                "reason": decision_text,
                "bullets": "[]",
                "warning": None,
                "image_asset_id": input_data.image_asset_id,
                "image_required": image_required,
                "image_status": image_status,
                "confidence": input_data.confidence,
                "status": input_data.status,
                "payload_json": json.dumps(payload, ensure_ascii=False),
            },
        )
        row = first_mapping(result)
        card_id = str(row["id"]) if row else ""

        question_status = "final_ready" if input_data.help_card_id else "card_ready"
        await execute(
            db,
            """
            UPDATE questions
            SET current_recommendation_card_id = :card_id,
                status = :question_status,
                updated_at = NOW()
            WHERE id = :question_id
            """,
            {
                "card_id": card_id,
                "question_id": context["question_id"],
                "question_status": question_status,
            },
        )
        if input_data.help_card_id is not None:
            await execute(
                db,
                """
                UPDATE help_cards
                SET final_recommendation_card_id = :card_id,
                    status = 'final_ready',
                    final_ready_at = NOW(),
                    updated_at = NOW()
                WHERE id = :help_card_id
                """,
                {"card_id": card_id, "help_card_id": input_data.help_card_id},
            )
        await commit(db)

        output = RecommendationCardOutput(
            card_id=card_id,
            question_id=str(context["question_id"]),
            user_id=str(user_id),
            item=input_data.item,
            decision_factor=input_data.decision_factor,
            image_asset_id=input_data.image_asset_id,
            image_required=image_required,
            image_status=image_status,
            evidence_ids=input_data.evidence_ids,
            confidence=input_data.confidence,
            status=input_data.status,
        )
        await finish_tool_call(
            tool_call_logger,
            tool_call_id=tool_call_id,
            status="succeeded",
            output_json=output.model_dump(mode="json"),
        )
        return output
    except Exception as error:
        await rollback(db)
        await finish_tool_call(
            tool_call_logger,
            tool_call_id=tool_call_id,
            status="failed",
            error_message=str(error),
        )
        raise


def _normalize_input(input_data: CreateRecommendationCardInput | Mapping[str, Any]) -> CreateRecommendationCardInput:
    if isinstance(input_data, CreateRecommendationCardInput):
        return input_data
    forbidden_fields = {"reasons", "bullets", "followups", "warning"} & set(input_data.keys())
    if forbidden_fields:
        raise ToolValidationError(
            "create_recommendation_card forbids display-only fields: "
            + ", ".join(sorted(forbidden_fields))
        )
    return CreateRecommendationCardInput.model_validate(dict(input_data))


async def _assert_displayable_non_ai_image_asset(db: SessionLike, image_asset_id: str) -> None:
    result = await execute(
        db,
        """
        SELECT id
        FROM image_assets
        WHERE id = :image_asset_id
          AND verified = TRUE
          AND verification_status = 'verified'
          AND displayable = TRUE
          AND is_ai_generated = FALSE
        LIMIT 1
        """,
        {"image_asset_id": image_asset_id},
    )
    if first_mapping(result) is None:
        raise ToolValidationError(
            "Recommendation card image_asset must be displayable, verified, and non-AI."
        )


async def _get_card_context(
    db: SessionLike,
    *,
    question_id: str | None,
    help_card_id: str | None,
) -> dict:
    if question_id is not None:
        question = await _get_question_context(db, question_id)
        return {
            "question_id": question["id"],
            "conversation_id": question["conversation_id"],
            "user_id": question["user_id"],
            "help_card_id": help_card_id,
        }
    if help_card_id is None:
        raise ToolValidationError("Question or help card is required before creating a recommendation card.")
    result = await execute(
        db,
        """
        SELECT
            help_cards.id AS help_card_id,
            help_cards.question_id,
            help_cards.conversation_id,
            help_cards.owner_user_id AS user_id
        FROM help_cards
        WHERE help_cards.id = :help_card_id
        LIMIT 1
        """,
        {"help_card_id": help_card_id},
    )
    row = first_mapping(result)
    if row is None:
        raise ToolValidationError("Help card is required before creating a recommendation card.")
    return row


async def _get_question_context(db: SessionLike, question_id: str) -> dict:
    result = await execute(
        db,
        """
        SELECT id, conversation_id, user_id
        FROM questions
        WHERE id = :question_id
        LIMIT 1
        """,
        {"question_id": question_id},
    )
    row = first_mapping(result)
    if row is None:
        raise ToolValidationError("Question is required before creating a recommendation card.")
    return row
