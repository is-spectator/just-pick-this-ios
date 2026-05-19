"""Routes for persisted light events."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api._service import call_service, resolve_service_handler
from app.schemas.cards import LightEventsResponse


router = APIRouter(tags=["light-events"])


@router.get("/light-events", response_model=LightEventsResponse)
async def light_events(
    user_id: str | None = None,
    device_uid: str | None = None,
    device_id: str | None = None,
    after: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
) -> LightEventsResponse:
    handler = resolve_service_handler("app.services.light_events", "list_light_events")
    return await call_service(
        handler,
        user_id=user_id,
        device_uid=device_uid or device_id,
        after=after,
        limit=limit,
        cursor=cursor,
    )
