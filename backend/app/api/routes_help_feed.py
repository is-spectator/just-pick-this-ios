"""Routes for help-feed cards and human one-liner evidence."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api._service import call_service, dump_model, resolve_service_handler
from app.schemas.cards import (
    AnswererQualityResponse,
    HelpCardDetail,
    HelpCardFinalAcceptRequest,
    HelpCardFinalAcceptResponse,
    HelpCardOneLinerRequest,
    HelpCardOneLinerResponse,
    HelpCardPublishRequest,
    HelpCardPublishResponse,
    HelpCardSkipRequest,
    HelpCardSkipResponse,
    HelpFeedResponse,
    RewardsMeResponse,
)


router = APIRouter(tags=["help-feed"])


@router.get("/help-feed", response_model=HelpFeedResponse)
async def help_feed(
    user_id: str | None = None,
    device_uid: str | None = None,
    device_id: str | None = None,
    limit: int = Query(default=10, ge=1, le=100),
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


@router.get("/help-cards/mine", response_model=HelpFeedResponse)
async def my_help_cards(
    user_id: str | None = None,
    device_uid: str | None = None,
    device_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
) -> HelpFeedResponse:
    handler = resolve_service_handler("app.services.help_feed", "list_my_help_cards")
    return await call_service(
        handler,
        user_id=user_id,
        device_uid=device_uid or device_id,
        limit=limit,
        cursor=cursor,
    )


@router.get("/help-cards/{help_card_id}", response_model=HelpCardDetail)
async def get_help_card(help_card_id: str) -> HelpCardDetail:
    handler = resolve_service_handler("app.services.help_feed", "get_help_card")
    return await call_service(handler, help_card_id)


@router.post("/help-cards/{help_card_id}/publish", response_model=HelpCardPublishResponse)
async def publish_help_card(
    help_card_id: str,
    payload: HelpCardPublishRequest,
) -> HelpCardPublishResponse:
    handler = resolve_service_handler("app.services.help_feed", "publish_help_card")
    return await call_service(handler, help_card_id, dump_model(payload))


@router.post("/help-cards/{help_card_id}/one-liner", response_model=HelpCardOneLinerResponse)
async def help_card_one_liner(
    help_card_id: str,
    payload: HelpCardOneLinerRequest,
) -> HelpCardOneLinerResponse:
    handler = resolve_service_handler("app.services.help_feed", "create_one_liner")
    return await call_service(handler, help_card_id, dump_model(payload))


@router.post("/help-cards/{help_card_id}/skip", response_model=HelpCardSkipResponse)
async def skip_help_card(
    help_card_id: str,
    payload: HelpCardSkipRequest,
) -> HelpCardSkipResponse:
    handler = resolve_service_handler("app.services.help_feed", "skip_help_card")
    return await call_service(handler, help_card_id, dump_model(payload))


@router.post("/help-cards/{help_card_id}/accept-final", response_model=HelpCardFinalAcceptResponse)
async def accept_final_recommendation(
    help_card_id: str,
    payload: HelpCardFinalAcceptRequest,
) -> HelpCardFinalAcceptResponse:
    handler = resolve_service_handler("app.services.help_feed", "accept_final_recommendation")
    return await call_service(handler, help_card_id, dump_model(payload))


@router.get("/rewards/me", response_model=RewardsMeResponse)
async def rewards_me(
    user_id: str | None = None,
    device_uid: str | None = None,
    device_id: str | None = None,
) -> RewardsMeResponse:
    handler = resolve_service_handler("app.services.help_feed", "get_my_rewards")
    return await call_service(handler, user_id=user_id, device_uid=device_uid or device_id)


@router.get("/answerers/me/quality", response_model=AnswererQualityResponse)
async def answerer_quality_me(
    user_id: str | None = None,
    device_uid: str | None = None,
    device_id: str | None = None,
) -> AnswererQualityResponse:
    handler = resolve_service_handler("app.services.answerer_quality", "get_answerer_quality")
    return await call_service(handler, user_id=user_id, device_uid=device_uid or device_id)
