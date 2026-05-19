from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.models import LightEvent
from app.services.runtime import resolve_request_user, serialize_light_event, session_scope


def list_light_events(
    *,
    user_id: str | None = None,
    device_uid: str | None = None,
    after: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    del after, cursor
    with session_scope() as session:
        user = resolve_request_user(session, user_id=user_id, device_uid=device_uid)
        if user is None:
            return {"items": [], "next_cursor": None}
        events = session.scalars(
            select(LightEvent)
            .where(LightEvent.user_id == user.id)
            .order_by(LightEvent.lit_at.desc())
            .limit(limit)
        )
        return {"items": [serialize_light_event(event) for event in events], "next_cursor": None}
