from __future__ import annotations

from collections.abc import Iterable

from app.ability.center import AbilityCenter
from app.ability.registry import DEFAULT_TOOL_NAMES, build_default_registry, get_tool_registry
from app.ability.schemas import AbilityTool


def build_ability_center(
    *,
    allowed_tools: Iterable[str] | None = None,
    tools: Iterable[AbilityTool] | dict[str, AbilityTool] | None = None,
) -> AbilityCenter:
    """Build the runtime ability boundary used by PipiLoop."""

    return AbilityCenter(
        tools if tools is not None else build_default_registry(),
        allowed_tools=allowed_tools,
    )


def get_ability_center(
    *,
    allowed_tools: Iterable[str] | None = None,
) -> AbilityCenter:
    return build_ability_center(allowed_tools=allowed_tools)


ABILITY_TOOLS = build_default_registry()


__all__ = [
    "ABILITY_TOOLS",
    "DEFAULT_TOOL_NAMES",
    "build_ability_center",
    "build_default_registry",
    "get_ability_center",
    "get_tool_registry",
]
