from __future__ import annotations

from app.ability.schemas import AbilityContext, AbilityTool
from app.ability.tools._common import maybe_override
from app.schemas.tools import SearchKnowledgeInput, SearchKnowledgeOutput


async def run_search_knowledge(
    context: AbilityContext,
    input_data: SearchKnowledgeInput,
) -> SearchKnowledgeOutput:
    handled, output = await maybe_override(context, "search_knowledge", input_data)
    if handled:
        return output

    if context.db is not None:
        from app.tools.knowledge import search_knowledge

        return await search_knowledge(
            context.db,
            input_data,
            tool_call_logger=context.tool_call_logger,
            retrieval_logger=context.retrieval_logger,
            agent_run_id=context.agent_run_id,
        )

    return SearchKnowledgeOutput(
        query=input_data.query,
        retrieval_run_id=None,
        hits=[],
    )


def build_search_knowledge_tool() -> AbilityTool:
    return AbilityTool(
        name="search_knowledge",
        input_schema=SearchKnowledgeInput,
        output_schema=SearchKnowledgeOutput,
        handler=run_search_knowledge,
        description="Retrieve persisted knowledge before choosing a Pipi tool call.",
    )


__all__ = ["build_search_knowledge_tool", "run_search_knowledge"]
