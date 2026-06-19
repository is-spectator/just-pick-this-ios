"""Chat and bootstrap routes for the Pipi runtime API."""

from __future__ import annotations

from fastapi import APIRouter, Header

from app.api._service import call_service, dump_model, resolve_service_handler
from app.schemas.chat import (
    BootstrapRequest,
    BootstrapResponse,
    ChatTurnRequest,
    ChatTurnResponse,
)


router = APIRouter(tags=["chat"])


@router.post("/bootstrap", response_model=BootstrapResponse)
async def bootstrap(payload: BootstrapRequest) -> BootstrapResponse:
    handler = resolve_service_handler("app.services.chat", "bootstrap")
    return await call_service(handler, dump_model(payload))


@router.post("/chat/turn", response_model=ChatTurnResponse, response_model_exclude_none=True)
async def chat_turn(
    payload: ChatTurnRequest,
    authorization: str | None = Header(default=None),
) -> ChatTurnResponse:
    handler = resolve_service_handler("app.services.chat", "run_chat_turn")
    data = dump_model(payload)
    if authorization:
        data["authorization"] = authorization
    return await call_service(handler, data)
