"""Routes for recommendation cards."""

from __future__ import annotations

from fastapi import APIRouter

from app.api._service import call_service, dump_model, resolve_service_handler
from app.schemas.cards import CardAcceptRequest, CardAcceptResponse, CardDetail


router = APIRouter(tags=["cards"])


@router.get("/cards/{id}", response_model=CardDetail)
async def get_card(id: str) -> CardDetail:
    handler = resolve_service_handler("app.services.cards", "get_card")
    return await call_service(handler, id)


@router.post("/cards/{id}/accept", response_model=CardAcceptResponse)
async def accept_card(id: str, payload: CardAcceptRequest) -> CardAcceptResponse:
    handler = resolve_service_handler("app.services.cards", "accept_card")
    return await call_service(handler, id, dump_model(payload))
