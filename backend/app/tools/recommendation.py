from __future__ import annotations

import json

from app.schemas.tools import CreateRecommendationCardInput, RecommendationCardOutput
from app.tools.errors import ToolValidationError
from app.tools.session import SessionLike, commit, execute, first_mapping, rollback
from app.tools.tool_call_logger import ToolCallLogger, finish_tool_call, start_tool_call


async def create_recommendation_card(
    db: SessionLike,
    input_data: CreateRecommendationCardInput,
    *,
    tool_call_logger: ToolCallLogger | None = None,
    agent_run_id: str | None = None,
) -> RecommendationCardOutput:
    tool_call_id = await start_tool_call(
        tool_call_logger,
        tool_name="create_recommendation_card",
        input_json=input_data.model_dump(mode="json"),
        agent_run_id=agent_run_id,
        question_id=input_data.question_id,
    )
    try:
        if input_data.image_required and not input_data.image_asset_id:
            raise ToolValidationError("Recommendation card image is required but no image_asset_id was provided.")
        if input_data.image_asset_id is not None:
            await _assert_displayable_non_ai_image_asset(db, input_data.image_asset_id)
        question = await _get_question_context(db, input_data.question_id)
        image_status = "attached" if input_data.image_asset_id else "missing"

        result = await execute(
            db,
            """
            INSERT INTO recommendation_cards (
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
                "question_id": input_data.question_id,
                "conversation_id": question["conversation_id"],
                "user_id": input_data.user_id,
                "agent_run_id": agent_run_id,
                "tool_call_id": tool_call_id,
                "source": input_data.source,
                "title": input_data.title,
                "subtitle": input_data.subtitle,
                "reason": input_data.reason,
                "bullets": json.dumps(input_data.bullets, ensure_ascii=False),
                "warning": input_data.warning,
                "image_asset_id": input_data.image_asset_id,
                "image_required": input_data.image_required,
                "image_status": image_status,
                "confidence": input_data.confidence,
                "status": input_data.status,
                "payload_json": json.dumps(
                    {"evidence_ids": input_data.evidence_ids},
                    ensure_ascii=False,
                ),
            },
        )
        row = first_mapping(result)
        card_id = str(row["id"]) if row else ""

        await execute(
            db,
            """
            UPDATE questions
            SET current_recommendation_card_id = :card_id,
                status = 'card_ready',
                updated_at = NOW()
            WHERE id = :question_id
            """,
            {"card_id": card_id, "question_id": input_data.question_id},
        )
        await commit(db)

        output = RecommendationCardOutput(
            card_id=card_id,
            question_id=input_data.question_id,
            user_id=input_data.user_id,
            title=input_data.title,
            subtitle=input_data.subtitle,
            reason=input_data.reason,
            bullets=input_data.bullets,
            image_asset_id=input_data.image_asset_id,
            image_required=input_data.image_required,
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


async def _assert_displayable_non_ai_image_asset(db: SessionLike, image_asset_id: str) -> None:
    result = await execute(
        db,
        """
        SELECT id
        FROM image_assets
        WHERE id = :image_asset_id
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


async def _get_question_context(db: SessionLike, question_id: str | None) -> dict:
    if question_id is None:
        raise ToolValidationError("Question is required before creating a recommendation card.")
    result = await execute(
        db,
        """
        SELECT id, conversation_id
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
