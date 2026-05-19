"""Routes for help-feed cards and human one-liner evidence."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api._service import call_service, dump_model, resolve_service_handler
from app.schemas.cards import (
    HelpCardOneLinerRequest,
    HelpCardOneLinerResponse,
    HelpFeedResponse,
)


router = APIRouter(tags=["help-feed"])


@router.get("/help-feed", response_model=HelpFeedResponse)
async def help_feed(
    user_id: str | None = None,
    device_uid: str | None = None,
    device_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
) -> HelpFeedResponse:
    handler = resolve_service_handler("app.services.help_feed", "list_help_feed")
    return await call_service(
        handler,
        user_id=user_id,
        device_uid=device_uid or device_id,
        limit=limit,
        cursor=cursor,
    )


@router.post("/help-cards/{id}/one-liner", response_model=HelpCardOneLinerResponse)
async def help_card_one_liner(
    id: str,
    payload: HelpCardOneLinerRequest,
) -> HelpCardOneLinerResponse:
    handler = resolve_service_handler("app.services.help_feed", "create_one_liner")
    return await call_service(handler, id, dump_model(payload))
