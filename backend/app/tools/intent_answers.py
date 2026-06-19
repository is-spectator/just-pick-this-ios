from __future__ import annotations

import json
from uuid import uuid4

from app.schemas.tools import SaveIntentAnswerInput, SaveIntentAnswerOutput
from app.tools.errors import ToolNotFoundError, ToolValidationError
from app.tools.session import SessionLike, commit, execute, first_mapping, rollback
from app.tools.tool_call_logger import (
    ToolCallLogger,
    ensure_tool_call_logger,
    finish_tool_call,
    start_tool_call,
)


async def save_intent_answer(
    db: SessionLike,
    input_data: SaveIntentAnswerInput,
    *,
    tool_call_logger: ToolCallLogger | None = None,
    agent_run_id: str | None = None,
) -> SaveIntentAnswerOutput:
    tool_call_logger = ensure_tool_call_logger(
        db,
        tool_call_logger,
        agent_run_id=agent_run_id,
    )
    tool_call_id = await start_tool_call(
        tool_call_logger,
        tool_name="save_intent_answer",
        input_json=input_data.model_dump(mode="json"),
        agent_run_id=agent_run_id,
        question_id=input_data.question_id,
        help_request_id=input_data.help_card_id,
    )
    try:
        context = await _resolve_answer_context(db, input_data)
        if input_data.image_asset_id is not None:
            await _assert_displayable_non_ai_image_asset(db, input_data.image_asset_id)

        intent_id = await _resolve_intent_id(db, input_data)
        answer_id = str(uuid4())
        evidence_json = {
            **input_data.metadata,
            "source_type": "pipi_saved_intent_answer",
            "help_card_id": input_data.help_card_id,
            "question_id": context.get("question_id"),
            "conversation_id": context.get("conversation_id") or input_data.conversation_id,
            "evidence_answer_ids": input_data.evidence_answer_ids,
        }
        source_type = str(input_data.metadata.get("source_type") or "pipi_saved_intent_answer")
        source_ref_id = input_data.metadata.get("source_ref_id") or input_data.help_card_id or input_data.question_id
        answer_title = str(input_data.metadata.get("answer_title") or input_data.answer_text[:80])
        answer_summary = str(input_data.metadata.get("answer_summary") or input_data.answer_text)
        constraints_value = input_data.metadata.get("constraints_json") or input_data.metadata.get("constraints") or {}
        constraints_json = constraints_value if isinstance(constraints_value, dict) else {}
        confidence_value = input_data.metadata.get("confidence")
        confidence = float(confidence_value) if isinstance(confidence_value, int | float) else None

        await execute(
            db,
            """
            INSERT INTO intent_answers (
                id,
                intent_id,
                image_asset_id,
                answer_text,
                intent_key,
                intent_text,
                answer_title,
                answer_summary,
                constraints_json,
                source_type,
                source_ref_id,
                confidence,
                success_count,
                rejection_count,
                locale,
                tags_json,
                evidence_json,
                priority,
                is_active,
                created_at,
                updated_at
            )
            VALUES (
                :id,
                :intent_id,
                :image_asset_id,
                :answer_text,
                :intent_key,
                :intent_text,
                :answer_title,
                :answer_summary,
                CAST(:constraints_json AS JSONB),
                :source_type,
                :source_ref_id,
                :confidence,
                :success_count,
                :rejection_count,
                :locale,
                CAST(:tags_json AS JSONB),
                CAST(:evidence_json AS JSONB),
                :priority,
                :is_active,
                NOW(),
                NOW()
            )
            """,
            {
                "id": answer_id,
                "intent_id": intent_id,
                "image_asset_id": input_data.image_asset_id,
                "answer_text": input_data.answer_text,
                "intent_key": input_data.intent_key,
                "intent_text": input_data.intent_name,
                "answer_title": answer_title,
                "answer_summary": answer_summary,
                "constraints_json": json.dumps(constraints_json, ensure_ascii=False),
                "source_type": source_type,
                "source_ref_id": str(source_ref_id) if source_ref_id else None,
                "confidence": confidence,
                "success_count": 0,
                "rejection_count": 0,
                "locale": input_data.locale,
                "tags_json": json.dumps(input_data.tags, ensure_ascii=False),
                "evidence_json": json.dumps(evidence_json, ensure_ascii=False),
                "priority": input_data.priority,
                "is_active": input_data.is_active,
            },
        )

        if input_data.help_card_id is not None:
            await _mark_help_answers_used(
                db,
                help_card_id=input_data.help_card_id,
                evidence_answer_ids=input_data.evidence_answer_ids,
            )

        await commit(db)

        output = SaveIntentAnswerOutput(
            intent_answer_id=answer_id,
            intent_id=str(intent_id),
            help_card_id=input_data.help_card_id,
            question_id=str(context["question_id"]) if context.get("question_id") else None,
            answer_text=input_data.answer_text,
            status="persisted",
            evidence_answer_ids=input_data.evidence_answer_ids,
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


async def _resolve_answer_context(
    db: SessionLike,
    input_data: SaveIntentAnswerInput,
) -> dict[str, str | None]:
    if input_data.help_card_id is not None:
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
            {"help_card_id": input_data.help_card_id},
        )
        row = first_mapping(result)
        if row is None:
            raise ToolNotFoundError("Help card not found.")
        return {key: str(value) if value is not None else None for key, value in row.items()}

    if input_data.question_id is not None:
        result = await execute(
            db,
            """
            SELECT id AS question_id, conversation_id, user_id
            FROM questions
            WHERE id = :question_id
            LIMIT 1
            """,
            {"question_id": input_data.question_id},
        )
        row = first_mapping(result)
        if row is None:
            raise ToolNotFoundError("Question not found.")
        return {key: str(value) if value is not None else None for key, value in row.items()}

    return {
        "help_card_id": None,
        "question_id": None,
        "conversation_id": input_data.conversation_id,
        "user_id": None,
    }


async def _resolve_intent_id(db: SessionLike, input_data: SaveIntentAnswerInput) -> str:
    if input_data.intent_id is not None:
        result = await execute(
            db,
            "SELECT id FROM intents WHERE id = :intent_id LIMIT 1",
            {"intent_id": input_data.intent_id},
        )
        row = first_mapping(result)
        if row is None:
            raise ToolNotFoundError("Intent not found.")
        return str(row["id"])

    result = await execute(
        db,
        "SELECT id FROM intents WHERE key = :intent_key LIMIT 1",
        {"intent_key": input_data.intent_key},
    )
    row = first_mapping(result)
    if row is not None:
        return str(row["id"])

    intent_id = str(uuid4())
    await execute(
        db,
        """
        INSERT INTO intents (
            id,
            key,
            name,
            description,
            examples_json,
            is_active,
            created_at,
            updated_at
        )
        VALUES (
            :id,
            :key,
            :name,
            :description,
            CAST(:examples_json AS JSONB),
            TRUE,
            NOW(),
            NOW()
        )
        """,
        {
            "id": intent_id,
            "key": input_data.intent_key,
            "name": input_data.intent_name,
            "description": "Finalized answer saved from Pipi help-card evidence.",
            "examples_json": "[]",
        },
    )
    return intent_id


async def _mark_help_answers_used(
    db: SessionLike,
    *,
    help_card_id: str,
    evidence_answer_ids: list[str],
) -> None:
    for answer_id in evidence_answer_ids:
        await execute(
            db,
            """
            UPDATE help_answers
            SET status = 'used',
                reward_status = 'granted'
            WHERE id = :answer_id
              AND help_card_id = :help_card_id
            """,
            {"answer_id": answer_id, "help_card_id": help_card_id},
        )


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
        raise ToolValidationError("Intent answer image_asset must be displayable, verified, and non-AI.")
