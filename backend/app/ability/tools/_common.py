from __future__ import annotations

import hashlib
import inspect
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from app.ability.schemas import AbilityContext


def stable_stub_id(prefix: str, *parts: Any) -> str:
    body = "|".join(str(part) for part in parts if part is not None and str(part))
    digest = hashlib.sha1(body.encode("utf-8")).hexdigest()[:12] if body else "empty"
    return f"stub:{prefix}:{digest}"


async def maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def maybe_override(
    context: AbilityContext,
    tool_name: str,
    input_data: BaseModel,
) -> tuple[bool, Any]:
    handlers = context.metadata.get("ability_tool_handlers") or {}
    handler = handlers.get(tool_name) if isinstance(handlers, dict) else None
    if handler is None:
        return False, None
    return True, await maybe_await(handler(context, input_data))


def metadata_int(context: AbilityContext, key: str, default: int) -> int:
    value = context.metadata.get(key)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def metadata_mapping(context: AbilityContext, key: str) -> dict[str, Any]:
    value = context.metadata.get(key)
    return dict(value) if isinstance(value, dict) else {}


PersistedTool = Callable[..., Any]


__all__ = [
    "PersistedTool",
    "maybe_await",
    "maybe_override",
    "metadata_int",
    "metadata_mapping",
    "stable_stub_id",
]
