from __future__ import annotations

import json
from uuid import uuid4

from app.schemas.tools import (
    DraftHelpCardInput,
    HelpCardOutput,
    PublishHelpCardInput,
    SubmitOneLinerAnswerInput,
    SubmitOneLinerAnswerOutput,
    UpdateHelpCardInput,
)
from app.tools.errors import ToolConflictError, ToolForbiddenError, ToolNotFoundError
from app.tools.session import SessionLike, commit, execute, first_mapping, rollback
from app.tools.tool_call_logger import (
    ToolCallLogger,
    ensure_tool_call_logger,
    finish_tool_call,
    start_tool_call,
)


async def draft_help_card(
    db: SessionLike,
    input_data: DraftHelpCardInput,
    *,
    tool_call_logger: ToolCallLogger | None = None,
    agent_run_id: str | None = None,
) -> HelpCardOutput:
    tool_call_logger = ensure_tool_call_logger(
        db,
        tool_call_logger,
        agent_run_id=agent_run_id,
    )
    tool_call_id = await start_tool_call(
        tool_call_logger,
        tool_name="draft_help_card",
        input_json=input_data.model_dump(mode="json"),
        agent_run_id=agent_run_id,
        question_id=input_data.question_id,
    )
    try:
        question = await _get_question_context(db, input_data.question_id)
        result = await execute(
            db,
            """
            INSERT INTO help_cards (
                id,
                question_id,
                conversation_id,
                owner_user_id,
                title,
                prompt,
                context_text,
                status,
                answer_count,
                min_answers_required,
                payload_json,
                created_at,
                updated_at
            )
            VALUES (
                :id,
                :question_id,
                :conversation_id,
                :owner_user_id,
                :title,
                :prompt,
                :context_text,
                'draft',
                0,
                :min_answers_required,
                CAST(:payload_json AS JSONB),
                NOW(),
                NOW()
            )
            RETURNING id
            """,
            {
                **input_data.model_dump(),
                "id": str(uuid4()),
                "conversation_id": question["conversation_id"],
                "prompt": input_data.title,
                "context_text": input_data.context_text,
                "payload_json": json.dumps(
                    {
                        "context": input_data.context,
                        "wants": input_data.wants,
                        "avoids": input_data.avoids,
                        "constraints": input_data.constraints,
                        "revision": input_data.revision,
                        "reward": input_data.reward,
                        "answer_stats": input_data.answer_stats,
                    },
                    ensure_ascii=False,
                ),
            },
        )
        row = first_mapping(result)
        help_card_id = str(row["id"]) if row else ""
        await execute(
            db,
            """
            UPDATE questions
            SET current_help_card_id = :help_card_id,
                status = 'ask_draft_ready',
                updated_at = NOW()
            WHERE id = :question_id
            """,
            {"help_card_id": help_card_id, "question_id": input_data.question_id},
        )
        await commit(db)
        output = HelpCardOutput(
            help_card_id=help_card_id,
            question_id=input_data.question_id,
            owner_user_id=input_data.owner_user_id,
            title=input_data.title,
            context_text=input_data.context_text,
            status="draft",
            min_answers_required=input_data.min_answers_required,
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


async def update_help_card(
    db: SessionLike,
    input_data: UpdateHelpCardInput,
    *,
    tool_call_logger: ToolCallLogger | None = None,
    agent_run_id: str | None = None,
) -> HelpCardOutput:
    tool_call_logger = ensure_tool_call_logger(
        db,
        tool_call_logger,
        agent_run_id=agent_run_id,
    )
    tool_call_id = await start_tool_call(
        tool_call_logger,
        tool_name="update_help_card",
        input_json=input_data.model_dump(mode="json"),
        agent_run_id=agent_run_id,
        help_request_id=input_data.help_card_id,
    )
    try:
        help_card = await _get_help_card(db, input_data.help_card_id)
        if (
            input_data.owner_user_id is not None
            and str(help_card["owner_user_id"]) != input_data.owner_user_id
        ):
            raise ToolForbiddenError("Only the help card owner can update it.")
        if help_card["status"] != "draft":
            raise ToolConflictError("Only draft help cards can be updated.")

        result = await execute(
            db,
            """
            UPDATE help_cards
            SET title = COALESCE(:title, title),
                prompt = COALESCE(:title, prompt),
                context_text = COALESCE(:context_text, context_text),
                min_answers_required = COALESCE(:min_answers_required, min_answers_required),
                updated_at = NOW()
            WHERE id = :help_card_id
            RETURNING
                id,
                question_id,
                owner_user_id,
                title,
                context_text,
                status,
                answer_count,
                min_answers_required,
                published_at
            """,
            {
                "help_card_id": input_data.help_card_id,
                "title": input_data.title,
                "context_text": input_data.context_text,
                "min_answers_required": input_data.min_answers_required,
            },
        )
        updated = first_mapping(result)
        if updated is None:
            raise ToolNotFoundError("Help card not found.")
        await execute(
            db,
            """
            UPDATE questions
            SET current_help_card_id = :help_card_id,
                status = 'ask_draft_ready',
                updated_at = NOW()
            WHERE id = :question_id
            """,
            {"help_card_id": input_data.help_card_id, "question_id": updated["question_id"]},
        )
        await commit(db)

        output = HelpCardOutput(
            help_card_id=str(updated["id"]),
            question_id=str(updated["question_id"]),
            owner_user_id=str(updated["owner_user_id"]),
            title=updated["title"],
            context_text=updated["context_text"],
            status=updated["status"],
            answer_count=updated["answer_count"],
            min_answers_required=updated["min_answers_required"],
            published_at=updated.get("published_at"),
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


async def publish_help_card(
    db: SessionLike,
    input_data: PublishHelpCardInput,
    *,
    tool_call_logger: ToolCallLogger | None = None,
    agent_run_id: str | None = None,
) -> HelpCardOutput:
    tool_call_logger = ensure_tool_call_logger(
        db,
        tool_call_logger,
        agent_run_id=agent_run_id,
    )
    tool_call_id = await start_tool_call(
        tool_call_logger,
        tool_name="publish_help_card",
        input_json=input_data.model_dump(mode="json"),
        agent_run_id=agent_run_id,
        help_request_id=input_data.help_card_id,
    )
    try:
        help_request = await _get_help_card(db, input_data.help_card_id)
        if (
            input_data.owner_user_id is not None
            and str(help_request["owner_user_id"]) != input_data.owner_user_id
        ):
            raise ToolForbiddenError("Only the help card owner can publish it.")
        if help_request["status"] != "draft":
            raise ToolConflictError("Only draft help cards can be published.")

        result = await execute(
            db,
            """
            UPDATE help_cards
            SET status = 'published',
                published_at = NOW(),
                updated_at = NOW()
            WHERE id = :help_card_id
            RETURNING published_at
            """,
            {"help_card_id": input_data.help_card_id},
        )
        published = first_mapping(result) or {}
        await execute(
            db,
            """
            UPDATE questions
            SET current_help_card_id = :help_card_id,
                status = 'help_published',
                updated_at = NOW()
            WHERE id = :question_id
            """,
            {
                "help_card_id": input_data.help_card_id,
                "question_id": help_request["question_id"],
            },
        )
        await commit(db)

        output = HelpCardOutput(
            help_card_id=input_data.help_card_id,
            question_id=str(help_request["question_id"]),
            owner_user_id=str(help_request["owner_user_id"]),
            title=help_request["title"],
            context_text=help_request["context_text"],
            status="published",
            answer_count=help_request["answer_count"],
            min_answers_required=help_request["min_answers_required"],
            published_at=published.get("published_at"),
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


async def submit_one_liner_answer(
    db: SessionLike,
    input_data: SubmitOneLinerAnswerInput,
    *,
    tool_call_logger: ToolCallLogger | None = None,
    agent_run_id: str | None = None,
) -> SubmitOneLinerAnswerOutput:
    tool_call_logger = ensure_tool_call_logger(
        db,
        tool_call_logger,
        agent_run_id=agent_run_id,
    )
    tool_call_id = await start_tool_call(
        tool_call_logger,
        tool_name="submit_one_liner_answer",
        input_json=input_data.model_dump(mode="json"),
        agent_run_id=agent_run_id,
        help_request_id=input_data.help_card_id,
    )
    try:
        help_request = await _get_help_card(db, input_data.help_card_id)
        if str(help_request["owner_user_id"]) == input_data.answer_user_id:
            raise ToolForbiddenError("Owner cannot answer their own help card.")
        if help_request["status"] not in {"published", "collecting"}:
            raise ToolConflictError("Help card is not accepting answers.")
        if await _has_answered(db, input_data.help_card_id, input_data.answer_user_id):
            raise ToolConflictError("User already answered this help card.")

        result = await execute(
            db,
            """
            INSERT INTO help_answers (
                id,
                help_card_id,
                answer_user_id,
                raw_text,
                normalized_text,
                status,
                reward_status,
                evidence_json,
                created_at
            )
            VALUES (
                :id,
                :help_card_id,
                :answer_user_id,
                :raw_text,
                :normalized_text,
                'submitted',
                'pending',
                CAST(:evidence_json AS JSONB),
                NOW()
            )
            RETURNING id
            """,
            {
                **input_data.model_dump(),
                "id": str(uuid4()),
                "evidence_json": '{"evidence_type": "human_one_liner"}',
            },
        )
        row = first_mapping(result)
        answer_id = str(row["id"]) if row else ""

        update_result = await execute(
            db,
            """
            UPDATE help_cards
            SET answer_count = answer_count + 1,
                status = 'collecting',
                updated_at = NOW()
            WHERE id = :help_card_id
            RETURNING answer_count, min_answers_required
            """,
            {"help_card_id": input_data.help_card_id},
        )
        counts = first_mapping(update_result) or {
            "answer_count": help_request["answer_count"] + 1,
            "min_answers_required": help_request["min_answers_required"],
        }
        await execute(
            db,
            """
            UPDATE questions
            SET status = 'collecting_answers',
                updated_at = NOW()
            WHERE id = :question_id
            """,
            {"question_id": help_request["question_id"]},
        )
        await commit(db)

        answer_count = int(counts["answer_count"])
        min_required = int(counts["min_answers_required"])
        output = SubmitOneLinerAnswerOutput(
            help_answer_id=answer_id,
            help_card_id=input_data.help_card_id,
            answer_user_id=input_data.answer_user_id,
            raw_text=input_data.raw_text,
            normalized_text=input_data.normalized_text,
            status="submitted",
            reward_status="pending",
            answer_count=answer_count,
            finalization_ready=answer_count >= min_required,
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


async def _get_help_card(db: SessionLike, help_card_id: str) -> dict:
    result = await execute(
        db,
        """
        SELECT
            id,
            question_id,
            owner_user_id,
            title,
            context_text,
            status,
            answer_count,
            min_answers_required,
            published_at
        FROM help_cards
        WHERE id = :help_card_id
        LIMIT 1
        """,
        {"help_card_id": help_card_id},
    )
    row = first_mapping(result)
    if row is None:
        raise ToolNotFoundError("Help card not found.")
    return row


async def _has_answered(db: SessionLike, help_card_id: str, answer_user_id: str) -> bool:
    result = await execute(
        db,
        """
        SELECT id
        FROM help_answers
        WHERE help_card_id = :help_card_id
          AND answer_user_id = :answer_user_id
        LIMIT 1
        """,
        {"help_card_id": help_card_id, "answer_user_id": answer_user_id},
    )
    return first_mapping(result) is not None


async def _get_question_context(db: SessionLike, question_id: str) -> dict:
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
        raise ToolNotFoundError("Question not found.")
    return row
