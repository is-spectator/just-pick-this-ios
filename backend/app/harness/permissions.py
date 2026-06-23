from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


ALLOW_ALL_TOOL = "*"


class HarnessPermissionError(Exception):
    code = "tool_not_allowed"


class PermissionDecision(BaseModel):
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    allowed: bool
    tool_name: str
    allowed_tools: list[str] = Field(default_factory=list)
    reason: str
    code: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.allowed


ToolPermissionDecision = PermissionDecision


def normalize_allowed_tools(allowed_tools: Iterable[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for tool in allowed_tools or []:
        name = str(tool).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        normalized.append(name)
    return normalized


def check_tool_permission(
    tool_name: str,
    allowed_tools: Iterable[str] | None,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> PermissionDecision:
    name = str(tool_name).strip()
    allowed = normalize_allowed_tools(allowed_tools)
    is_allowed = bool(name) and (ALLOW_ALL_TOOL in allowed or name in allowed)
    return PermissionDecision(
        allowed=is_allowed,
        tool_name=name,
        allowed_tools=allowed,
        reason="tool_allowed_by_input_gate" if is_allowed else "tool_not_allowed_by_input_gate",
        code=None if is_allowed else HarnessPermissionError.code,
        metadata=dict(metadata or {}),
    )


def check_tool_allowed(
    tool_name: str,
    allowed_tools: Iterable[str] | None,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> PermissionDecision:
    return check_tool_permission(tool_name, allowed_tools, metadata=metadata)


def is_tool_allowed(tool_name: str, allowed_tools: Iterable[str] | None) -> bool:
    return check_tool_permission(tool_name, allowed_tools).allowed


def require_tool_permission(
    tool_name: str,
    allowed_tools: Iterable[str] | None,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> PermissionDecision:
    decision = check_tool_permission(tool_name, allowed_tools, metadata=metadata)
    if not decision.allowed:
        raise HarnessPermissionError(decision.reason)
    return decision


def filter_allowed_tools(
    requested_tools: Iterable[str],
    allowed_tools: Iterable[str] | None,
) -> list[str]:
    allowed = set(normalize_allowed_tools(allowed_tools))
    if ALLOW_ALL_TOOL in allowed:
        return normalize_allowed_tools(requested_tools)
    return [tool for tool in normalize_allowed_tools(requested_tools) if tool in allowed]


__all__ = [
    "ALLOW_ALL_TOOL",
    "HarnessPermissionError",
    "PermissionDecision",
    "ToolPermissionDecision",
    "check_tool_allowed",
    "check_tool_permission",
    "filter_allowed_tools",
    "is_tool_allowed",
    "normalize_allowed_tools",
    "require_tool_permission",
]
