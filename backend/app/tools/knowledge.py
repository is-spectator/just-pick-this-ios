from __future__ import annotations

from app.retrieval import RetrievalLogger, RetrievalService
from app.schemas.tools import SearchKnowledgeInput, SearchKnowledgeOutput
from app.tools.session import SessionLike
from app.tools.tool_call_logger import (
    ToolCallLogger,
    ensure_tool_call_logger,
    finish_tool_call,
    start_tool_call,
)


async def search_knowledge(
    db: SessionLike,
    input_data: SearchKnowledgeInput,
    *,
    tool_call_logger: ToolCallLogger | None = None,
    retrieval_logger: RetrievalLogger | None = None,
    agent_run_id: str | None = None,
) -> SearchKnowledgeOutput:
    tool_call_logger = ensure_tool_call_logger(
        db,
        tool_call_logger,
        agent_run_id=agent_run_id,
    )
    tool_call_id = await start_tool_call(
        tool_call_logger,
        tool_name="search_knowledge",
        input_json=input_data.model_dump(mode="json"),
        agent_run_id=agent_run_id,
        question_id=input_data.question_id,
    )
    try:
        active_retrieval_logger = retrieval_logger
        if active_retrieval_logger is None and agent_run_id is not None:
            active_retrieval_logger = RetrievalLogger(db, agent_run_id=agent_run_id)
        service = RetrievalService(db, active_retrieval_logger)
        output = await service.search_knowledge(input_data)
        await finish_tool_call(
            tool_call_logger,
            tool_call_id=tool_call_id,
            status="succeeded",
            output_json=output.model_dump(mode="json"),
        )
        return output
    except Exception as error:
        await finish_tool_call(
            tool_call_logger,
            tool_call_id=tool_call_id,
            status="failed",
            error_message=str(error),
        )
        raise
