from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException

from app.models import RecommendationCard
from app.services.runtime import serialize_card_detail, session_scope, utcnow
from app.services.user_events import record_user_behavior_event


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
    payload = payload or {}
    with session_scope() as session:
        card = session.get(RecommendationCard, uuid.UUID(id))
        if card is None:
            raise HTTPException(status_code=404, detail="card_not_found")
        already_accepted = card.status == "accepted" and card.accepted_at is not None
        card.status = "accepted"
        card.accepted_at = utcnow()
        card.question.status = "completed"
        record_user_behavior_event(
            session,
            event_type="recommendation_card_accepted",
            user_id=_optional_uuid(payload.get("user_id")) or card.user_id,
            device_uid=payload.get("device_uid") or payload.get("device_id"),
            conversation_id=card.conversation_id,
            recommendation_card_id=card.id,
            source="api",
            payload_json={
                "status": "completed",
                "already_accepted": already_accepted,
                **dict(payload.get("metadata") or {}),
            },
        )
        session.flush()
        return {"card_id": str(card.id), "accepted": True, "metadata": {"status": "completed"}}


def _optional_uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None
