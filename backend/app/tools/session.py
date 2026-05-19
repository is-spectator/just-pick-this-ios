from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.sql.elements import TextClause


class SessionLike(Protocol):
    def execute(self, statement: Any, parameters: Mapping[str, Any] | None = None) -> Any: ...


async def maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def execute(
    db: SessionLike,
    statement: str | TextClause,
    parameters: Mapping[str, Any] | None = None,
) -> Any:
    clause = text(statement) if isinstance(statement, str) else statement
    return await maybe_await(db.execute(clause, parameters or {}))


async def commit(db: Any) -> None:
    method = getattr(db, "commit", None)
    if method is not None:
        await maybe_await(method())


async def rollback(db: Any) -> None:
    method = getattr(db, "rollback", None)
    if method is not None:
        await maybe_await(method())


def first_mapping(result: Any) -> dict[str, Any] | None:
    mappings = getattr(result, "mappings", None)
    if mappings is not None:
        row = mappings().first()
    else:
        row = result.first() if hasattr(result, "first") else None
    return dict(row) if row is not None else None


def all_mappings(result: Any) -> list[dict[str, Any]]:
    mappings = getattr(result, "mappings", None)
    rows = mappings().all() if mappings is not None else result.all()
    return [dict(row) for row in rows]
