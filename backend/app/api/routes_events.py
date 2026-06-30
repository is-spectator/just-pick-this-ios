"""Routes for product behavior events."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api._service import call_service, dump_model, resolve_service_handler
from app.schemas.cards import FavoriteChoiceListResponse, UserBehaviorEventRequest, UserBehaviorEventResponse


router = APIRouter(tags=["events"])


@router.post("/events", response_model=UserBehaviorEventResponse)
async def create_event(payload: UserBehaviorEventRequest) -> UserBehaviorEventResponse:
    handler = resolve_service_handler("app.services.user_events", "create_user_event")
    return await call_service(handler, dump_model(payload))


@router.get("/favorites/mine", response_model=FavoriteChoiceListResponse)
async def my_favorites(
    user_id: str | None = None,
    device_uid: str | None = None,
    device_id: str | None = None,
    limit: int = Query(default=80, ge=1, le=100),
    cursor: str | None = None,
) -> FavoriteChoiceListResponse:
    handler = resolve_service_handler("app.services.user_events", "list_user_favorites")
    return await call_service(
        handler,
        user_id=user_id,
        device_uid=device_uid or device_id,
        limit=limit,
        cursor=cursor,
    )
