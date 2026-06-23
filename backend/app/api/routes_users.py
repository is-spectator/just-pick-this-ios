"""Routes for user profile and preference memory."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api._service import call_service, resolve_service_handler
from app.schemas.cards import UserPreferencesResponse


router = APIRouter(tags=["users"])


@router.get("/users/preferences", response_model=UserPreferencesResponse)
async def get_user_preferences(
    device_uid: str | None = Query(default=None),
    device_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
) -> UserPreferencesResponse:
    handler = resolve_service_handler("app.services.user_events", "get_user_preferences")
    return await call_service(
        handler,
        {"device_uid": device_uid, "device_id": device_id, "user_id": user_id},
    )
