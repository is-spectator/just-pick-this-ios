"""Small helpers for routing to future service-layer handlers."""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from inspect import isawaitable
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel


ServiceHandler = Callable[..., Any]


def resolve_service_handler(module_name: str, handler_name: str) -> ServiceHandler:
    """Load a service handler lazily so missing future modules do not break imports."""

    try:
        module = import_module(module_name)
    except ImportError as exc:
        raise service_unavailable(module_name, handler_name) from exc

    handler = getattr(module, handler_name, None)
    if not callable(handler):
        raise service_unavailable(module_name, handler_name)

    return handler


async def call_service(handler: ServiceHandler, *args: Any, **kwargs: Any) -> Any:
    """Call a sync or async service handler."""

    result = handler(*args, **kwargs)
    if isawaitable(result):
        return await result
    return result


def dump_model(value: BaseModel | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return value.model_dump(mode="json", exclude_none=True)


def service_unavailable(module_name: str, handler_name: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={
            "code": "service_unavailable",
            "message": "Service handler is not wired yet.",
            "handler": f"{module_name}.{handler_name}",
        },
    )
