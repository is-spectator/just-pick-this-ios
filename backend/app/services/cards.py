from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException

from app.models import RecommendationCard
from app.services.runtime import serialize_card_detail, session_scope, utcnow


def get_card(id: str) -> dict[str, Any]:
    from app.services.smoke_runtime import get_smoke_card

    smoke_card = get_smoke_card(id)
    if smoke_card is not None:
        return smoke_card

    with session_scope() as session:
        card = session.get(RecommendationCard, uuid.UUID(id))
        if card is None:
            raise HTTPException(status_code=404, detail="card_not_found")
        card_detail = serialize_card_detail(card)
        return {"card": card_detail, **card_detail}


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
