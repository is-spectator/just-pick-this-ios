"""Routes for recommendation cards."""

from __future__ import annotations

from fastapi import APIRouter

from app.api._service import call_service, dump_model, resolve_service_handler
from app.schemas.cards import (
    CardAcceptRequest,
    CardAcceptResponse,
    CardDetail,
    CardFeedbackRequest,
    CardFeedbackResponse,
    CardPostReviewRequest,
)


router = APIRouter(tags=["cards"])


@router.get("/cards/{card_id}", response_model=CardDetail)
async def get_card(card_id: str) -> CardDetail:
    handler = resolve_service_handler("app.services.cards", "get_card")
    return await call_service(handler, card_id)


@router.post("/cards/{card_id}/accept", response_model=CardAcceptResponse)
async def accept_card(card_id: str, payload: CardAcceptRequest) -> CardAcceptResponse:
    handler = resolve_service_handler("app.services.cards", "accept_card")
    return await call_service(handler, card_id, dump_model(payload))


@router.post("/cards/{card_id}/reject", response_model=CardFeedbackResponse)
async def reject_card(card_id: str, payload: CardFeedbackRequest) -> CardFeedbackResponse:
    handler = resolve_service_handler("app.services.cards", "reject_card")
    return await call_service(handler, card_id, dump_model(payload))


@router.post("/cards/{card_id}/change", response_model=CardFeedbackResponse)
async def change_card(card_id: str, payload: CardFeedbackRequest) -> CardFeedbackResponse:
    handler = resolve_service_handler("app.services.cards", "change_card")
    return await call_service(handler, card_id, dump_model(payload))


@router.post("/cards/{card_id}/review", response_model=CardFeedbackResponse)
async def review_card(card_id: str, payload: CardPostReviewRequest) -> CardFeedbackResponse:
    handler = resolve_service_handler("app.services.cards", "review_card")
    return await call_service(handler, card_id, dump_model(payload))
