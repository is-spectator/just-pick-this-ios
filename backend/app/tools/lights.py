from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from app.schemas.tools import LightUserInput, LightUserOutput
from app.tools.session import SessionLike, commit, execute, first_mapping, rollback
from app.tools.tool_call_logger import (
    ToolCallLogger,
    ensure_tool_call_logger,
    finish_tool_call,
    start_tool_call,
)


async def light_user(
    db: SessionLike,
    input_data: LightUserInput,
    *,
    tool_call_logger: ToolCallLogger | None = None,
    agent_run_id: str | None = None,
) -> LightUserOutput:
    tool_call_logger = ensure_tool_call_logger(
        db,
        tool_call_logger,
        agent_run_id=agent_run_id,
    )
    tool_call_id = await start_tool_call(
        tool_call_logger,
        tool_name="light_user",
        input_json=input_data.model_dump(mode="json"),
        agent_run_id=agent_run_id,
        question_id=input_data.question_id,
        help_request_id=input_data.help_card_id,
    )
    try:
        result = await execute(
            db,
            """
            INSERT INTO light_events (
                id,
                user_id,
                conversation_id,
                question_id,
                help_card_id,
                recommendation_card_id,
                type,
                title,
                body,
                payload_json,
                lit_at,
                expires_at,
                created_at
            )
            VALUES (
                :id,
                :user_id,
                :conversation_id,
                :question_id,
                :help_card_id,
                :recommendation_card_id,
                :type,
                :title,
                :body,
                CAST(:payload_json AS JSONB),
                NOW(),
                :expires_at,
                NOW()
            )
            RETURNING id, lit_at
            """,
            {
                **input_data.model_dump(),
                "id": str(uuid4()),
                "payload_json": json.dumps(
                    {
                        **input_data.metadata,
                        "target_type": input_data.target_type,
                        "target_id": input_data.target_id,
                    },
                    ensure_ascii=False,
                ),
            },
        )
        row = first_mapping(result) or {}
        await commit(db)
        output = LightUserOutput(
            light_event_id=str(row.get("id", "")),
            user_id=input_data.user_id,
            type=input_data.type,
            title=input_data.title,
            body=input_data.body,
            lit_at=row.get("lit_at") or datetime.now(timezone.utc),
            expires_at=input_data.expires_at,
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
