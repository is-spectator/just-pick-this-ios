from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import HelpAnswer, HelpCard, RecommendationCard, UserBehaviorEvent
from app.services.runtime import ensure_user, session_scope


CORE_USER_EVENT_TYPES = {
    "recommendation_card_accepted",
    "recommendation_card_rejected",
    "recommendation_card_changed",
    "ask_human_requested",
    "help_card_published",
    "one_liner_submitted",
    "one_liner_reward_granted",
    "final_recommendation_accepted",
}


def create_user_event(payload: dict[str, Any]) -> dict[str, Any]:
    with session_scope() as session:
        event = record_user_behavior_event(
            session,
            event_type=str(payload.get("event_type") or ""),
            user_id=_optional_uuid(payload.get("user_id")),
            device_uid=payload.get("device_uid") or payload.get("device_id"),
            conversation_id=_optional_uuid(payload.get("conversation_id")),
            turn_id=_optional_uuid(payload.get("turn_id")),
            recommendation_card_id=_optional_uuid(payload.get("card_id") or payload.get("recommendation_card_id")),
            help_card_id=_optional_uuid(payload.get("help_card_id")),
            help_answer_id=_optional_uuid(payload.get("help_answer_id")),
            source=str(payload.get("source") or "api"),
            payload_json=dict(payload.get("metadata") or {}),
        )
        session.flush()
        return {"event": serialize_user_behavior_event(event), "accepted": True}


def record_user_behavior_event(
    session: Session,
    *,
    event_type: str,
    user_id: uuid.UUID | None = None,
    device_uid: str | None = None,
    conversation_id: uuid.UUID | None = None,
    turn_id: uuid.UUID | None = None,
    recommendation_card_id: uuid.UUID | None = None,
    help_card_id: uuid.UUID | None = None,
    help_answer_id: uuid.UUID | None = None,
    source: str = "api",
    payload_json: dict[str, Any] | None = None,
) -> UserBehaviorEvent:
    normalized_type = str(event_type or "").strip()
    if not normalized_type:
        raise HTTPException(status_code=422, detail="event_type_required")

    context = _resolve_context(
        session,
        user_id=user_id,
        device_uid=str(device_uid) if device_uid else None,
        conversation_id=conversation_id,
        recommendation_card_id=recommendation_card_id,
        help_card_id=help_card_id,
        help_answer_id=help_answer_id,
    )
    event = UserBehaviorEvent(
        user_id=context.get("user_id"),
        conversation_id=context.get("conversation_id"),
        turn_id=turn_id,
        recommendation_card_id=recommendation_card_id,
        help_card_id=context.get("help_card_id"),
        help_answer_id=help_answer_id,
        event_type=normalized_type,
        source=str(source or "api"),
        payload_json={
            **dict(payload_json or {}),
            "known_core_event": normalized_type in CORE_USER_EVENT_TYPES,
        },
    )
    session.add(event)
    return event


def serialize_user_behavior_event(event: UserBehaviorEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "event_type": event.event_type,
        "source": event.source,
        "user_id": str(event.user_id) if event.user_id else None,
        "conversation_id": str(event.conversation_id) if event.conversation_id else None,
        "turn_id": str(event.turn_id) if event.turn_id else None,
        "card_id": str(event.recommendation_card_id) if event.recommendation_card_id else None,
        "help_card_id": str(event.help_card_id) if event.help_card_id else None,
        "help_answer_id": str(event.help_answer_id) if event.help_answer_id else None,
        "metadata": event.payload_json or {},
        "created_at": event.created_at,
    }


def _resolve_context(
    session: Session,
    *,
    user_id: uuid.UUID | None,
    device_uid: str | None,
    conversation_id: uuid.UUID | None,
    recommendation_card_id: uuid.UUID | None,
    help_card_id: uuid.UUID | None,
    help_answer_id: uuid.UUID | None,
) -> dict[str, uuid.UUID | None]:
    resolved_user_id = user_id
    resolved_conversation_id = conversation_id
    resolved_help_card_id = help_card_id

    if recommendation_card_id is not None:
        card = session.get(RecommendationCard, recommendation_card_id)
        if card is None:
            raise HTTPException(status_code=404, detail="card_not_found")
        resolved_user_id = resolved_user_id or card.user_id
        resolved_conversation_id = resolved_conversation_id or card.conversation_id

    if help_card_id is not None:
        help_card = session.get(HelpCard, help_card_id)
        if help_card is None:
            raise HTTPException(status_code=404, detail="help_card_not_found")
        resolved_conversation_id = resolved_conversation_id or help_card.conversation_id

    if help_answer_id is not None:
        answer = session.get(HelpAnswer, help_answer_id)
        if answer is None:
            raise HTTPException(status_code=404, detail="help_answer_not_found")
        resolved_user_id = resolved_user_id or answer.answer_user_id
        resolved_help_card_id = resolved_help_card_id or answer.help_card_id
        if resolved_conversation_id is None and answer.help_card is not None:
            resolved_conversation_id = answer.help_card.conversation_id

    if resolved_user_id is None and device_uid:
        resolved_user_id = ensure_user(session, device_uid=device_uid).id

    return {
        "user_id": resolved_user_id,
        "conversation_id": resolved_conversation_id,
        "help_card_id": resolved_help_card_id,
    }


def _optional_uuid(value: Any) -> uuid.UUID | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return uuid.UUID(text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"invalid_uuid:{text}") from exc
