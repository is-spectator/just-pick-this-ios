from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException

from app.models import RecommendationCard
from app.services.runtime import serialize_card_detail, session_scope, utcnow


def get_card(id: str) -> dict[str, Any]:
    with session_scope() as session:
        card = session.get(RecommendationCard, uuid.UUID(id))
        if card is None:
            raise HTTPException(status_code=404, detail="card_not_found")
        return serialize_card_detail(card)


def accept_card(id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    del payload
    with session_scope() as session:
        card = session.get(RecommendationCard, uuid.UUID(id))
        if card is None:
            raise HTTPException(status_code=404, detail="card_not_found")
        card.status = "accepted"
        card.accepted_at = utcnow()
        card.question.status = "completed"
        return {"card_id": str(card.id), "accepted": True, "metadata": {"status": "completed"}}
