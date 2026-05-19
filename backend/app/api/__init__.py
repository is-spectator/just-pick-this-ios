"""Versioned API router aggregation."""

from fastapi import APIRouter

from app.api.routes_cards import router as cards_router
from app.api.routes_chat import router as chat_router
from app.api.routes_help_feed import router as help_feed_router
from app.api.routes_light_events import router as light_events_router


api_router = APIRouter(prefix="/v1")
api_router.include_router(chat_router)
api_router.include_router(help_feed_router)
api_router.include_router(light_events_router)
api_router.include_router(cards_router)

__all__ = ["api_router"]
