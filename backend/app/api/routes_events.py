"""Routes for product behavior events."""

from __future__ import annotations

from fastapi import APIRouter

from app.api._service import call_service, dump_model, resolve_service_handler
from app.schemas.cards import UserBehaviorEventRequest, UserBehaviorEventResponse


router = APIRouter(tags=["events"])


@router.post("/events", response_model=UserBehaviorEventResponse)
async def create_event(payload: UserBehaviorEventRequest) -> UserBehaviorEventResponse:
    handler = resolve_service_handler("app.services.user_events", "create_user_event")
    return await call_service(handler, dump_model(payload))
