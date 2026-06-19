from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from app.ability.schemas import AbilityContext, AbilityTool
from app.ability.tools._common import maybe_override, stable_stub_id
from app.schemas.tools import LightUserInput, LightUserOutput


async def run_light_user(
    context: AbilityContext,
    input_data: LightUserInput,
) -> LightUserOutput:
    handled, output = await maybe_override(context, "light_user", input_data)
    if handled:
        return output

    if context.db is not None:
        from app.tools.lights import light_user

        return await light_user(
            context.db,
            input_data,
            tool_call_logger=context.tool_call_logger,
            agent_run_id=context.agent_run_id,
        )

    return LightUserOutput(
        light_event_id=stable_stub_id(
            "light_event",
            input_data.user_id,
            input_data.type,
            input_data.target_id,
            input_data.recommendation_card_id,
        ),
        user_id=input_data.user_id,
        type=input_data.type,
        title=input_data.title,
        body=input_data.body,
        lit_at=datetime.now(timezone.utc),
        expires_at=input_data.expires_at,
    )


def adapt_light_user_input(
    payload: Mapping[str, Any],
    context: AbilityContext,
) -> Mapping[str, Any]:
    normalized = dict(payload)
    normalized.pop("user_turn_id", None)
    if not normalized.get("user_id") and context.metadata.get("user_id"):
        normalized["user_id"] = context.metadata["user_id"]
    if not normalized.get("conversation_id") and context.metadata.get("conversation_id"):
        normalized["conversation_id"] = context.metadata["conversation_id"]
    return normalized


def build_light_user_tool() -> AbilityTool:
    return AbilityTool(
        name="light_user",
        input_schema=LightUserInput,
        output_schema=LightUserOutput,
        handler=run_light_user,
        input_adapter=adapt_light_user_input,
        description="Create a light event for the user after a tool-visible state change.",
    )


__all__ = ["adapt_light_user_input", "build_light_user_tool", "run_light_user"]
