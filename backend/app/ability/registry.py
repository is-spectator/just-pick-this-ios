from __future__ import annotations

from collections.abc import Iterable

from app.ability.center import AbilityCenter
from app.ability.schemas import AbilityTool
from app.ability.tools import (
    build_create_recommendation_card_tool,
    build_draft_help_card_tool,
    build_finalize_help_card_tool,
    build_light_user_tool,
    build_publish_help_card_tool,
    build_save_intent_answer_tool,
    build_search_knowledge_tool,
    build_submit_one_liner_answer_tool,
    build_update_help_card_tool,
)


DEFAULT_TOOL_NAMES = (
    "search_knowledge",
    "create_recommendation_card",
    "draft_help_card",
    "update_help_card",
    "publish_help_card",
    "submit_one_liner_answer",
    "finalize_help_card",
    "save_intent_answer",
    "light_user",
)


def build_default_registry() -> dict[str, AbilityTool]:
    tools = [
        build_search_knowledge_tool(),
        build_create_recommendation_card_tool(),
        build_draft_help_card_tool(),
        build_update_help_card_tool(),
        build_publish_help_card_tool(),
        build_submit_one_liner_answer_tool(),
        build_finalize_help_card_tool(),
        build_save_intent_answer_tool(),
        build_light_user_tool(),
    ]
    return {tool.name: tool for tool in tools}


ABILITY_TOOLS = build_default_registry()


def get_tool_registry() -> dict[str, AbilityTool]:
    return build_default_registry()


def build_ability_center(
    *,
    allowed_tools: Iterable[str] | None = None,
) -> AbilityCenter:
    return AbilityCenter(build_default_registry(), allowed_tools=allowed_tools)


def get_ability_center(
    *,
    allowed_tools: Iterable[str] | None = None,
) -> AbilityCenter:
    return build_ability_center(allowed_tools=allowed_tools)


__all__ = [
    "ABILITY_TOOLS",
    "DEFAULT_TOOL_NAMES",
    "build_ability_center",
    "build_default_registry",
    "get_ability_center",
    "get_tool_registry",
]
