"""FastAPI backend package for 就选这个 / 皮皮 Agent Runtime.

Keep package import light. Importing a leaf module such as
``app.services.intent_router`` should not eagerly create the FastAPI app.
"""

from __future__ import annotations

from typing import Any

__all__ = ["app", "create_app"]


def create_app(*args: Any, **kwargs: Any) -> Any:
    from app.main import create_app as _create_app

    return _create_app(*args, **kwargs)


def __getattr__(name: str) -> Any:
    if name == "app":
        from app.main import app as _app

        return _app
    if name == "create_app":
        return create_app
    raise AttributeError(name)
