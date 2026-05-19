from __future__ import annotations

from typing import Any, Protocol
from uuid import uuid4

from app.schemas.tools import ToolCallRecord, ToolName
from app.tools.session import SessionLike, commit, execute, first_mapping


class ToolCallLogger(Protocol):
    async def start_tool_call(
        self,
        *,
        tool_name: ToolName,
        input_json: dict[str, Any],
        agent_run_id: str | None = None,
        question_id: str | None = None,
        help_request_id: str | None = None,
    ) -> ToolCallRecord | None: ...

    async def finish_tool_call(
        self,
        *,
        tool_call_id: str | None,
        status: str,
        output_json: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None: ...


class MemoryToolCallLogger:
    """Small protocol implementation for tests and deterministic first-stage runs."""

    def __init__(self) -> None:
        self.records: list[ToolCallRecord] = []

    async def start_tool_call(
        self,
        *,
        tool_name: ToolName,
        input_json: dict[str, Any],
        agent_run_id: str | None = None,
        question_id: str | None = None,
        help_request_id: str | None = None,
    ) -> ToolCallRecord:
        record = ToolCallRecord(
            id=str(uuid4()),
            tool_name=tool_name,
            input_json=input_json,
            status="running",
            agent_run_id=agent_run_id,
            question_id=question_id,
            help_request_id=help_request_id,
        )
        self.records.append(record)
        return record

    async def finish_tool_call(
        self,
        *,
        tool_call_id: str | None,
        status: str,
        output_json: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        if tool_call_id is None:
            return
        for index, record in enumerate(self.records):
            if record.id == tool_call_id:
                self.records[index] = record.model_copy(
                    update={
                        "status": status,
                        "output_json": output_json,
                        "error_message": error_message,
                    }
                )
                return


class SqlAlchemyToolCallLogger:
    def __init__(
        self,
        db: SessionLike,
        *,
        agent_run_id: str,
        turn_id: str | None = None,
        sequence_index: int = 0,
    ) -> None:
        self.db = db
        self.agent_run_id = agent_run_id
        self.turn_id = turn_id
        self.sequence_index = sequence_index

    async def start_tool_call(
        self,
        *,
        tool_name: ToolName,
        input_json: dict[str, Any],
        agent_run_id: str | None = None,
        question_id: str | None = None,
        help_request_id: str | None = None,
    ) -> ToolCallRecord | None:
        del question_id, help_request_id
        result = await execute(
            self.db,
            """
            INSERT INTO tool_calls (
                agent_run_id,
                turn_id,
                tool_name,
                arguments_json,
                status,
                sequence_index,
                started_at,
                created_at,
                updated_at
            )
            VALUES (
                :agent_run_id,
                :turn_id,
                :tool_name,
                CAST(:arguments_json AS JSONB),
                'running',
                :sequence_index,
                NOW(),
                NOW(),
                NOW()
            )
            RETURNING id, created_at, started_at
            """,
            {
                "agent_run_id": agent_run_id or self.agent_run_id,
                "turn_id": self.turn_id,
                "tool_name": tool_name,
                "arguments_json": _json_dump(input_json),
                "sequence_index": self.sequence_index,
            },
        )
        row = first_mapping(result)
        await commit(self.db)
        if row is None:
            return None
        return ToolCallRecord(
            id=str(row["id"]),
            tool_name=tool_name,
            input_json=input_json,
            status="running",
            agent_run_id=agent_run_id or self.agent_run_id,
            created_at=row.get("created_at") or row.get("started_at"),
        )

    async def finish_tool_call(
        self,
        *,
        tool_call_id: str | None,
        status: str,
        output_json: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        if tool_call_id is None:
            return
        await execute(
            self.db,
            """
            UPDATE tool_calls
            SET status = :status,
                result_json = CAST(:result_json AS JSONB),
                error_message = :error_message,
                finished_at = NOW(),
                updated_at = NOW()
            WHERE id = :tool_call_id
            """,
            {
                "tool_call_id": tool_call_id,
                "status": status,
                "result_json": _json_dump(output_json) if output_json is not None else None,
                "error_message": error_message,
            },
        )
        await commit(self.db)


async def start_tool_call(
    logger: ToolCallLogger | None,
    *,
    tool_name: ToolName,
    input_json: dict[str, Any],
    agent_run_id: str | None = None,
    question_id: str | None = None,
    help_request_id: str | None = None,
) -> str | None:
    if logger is None:
        return None
    record = await logger.start_tool_call(
        tool_name=tool_name,
        input_json=input_json,
        agent_run_id=agent_run_id,
        question_id=question_id,
        help_request_id=help_request_id,
    )
    return record.id if record is not None else None


async def finish_tool_call(
    logger: ToolCallLogger | None,
    *,
    tool_call_id: str | None,
    status: str,
    output_json: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> None:
    if logger is None:
        return
    await logger.finish_tool_call(
        tool_call_id=tool_call_id,
        status=status,
        output_json=output_json,
        error_message=error_message,
    )


def _json_dump(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)
