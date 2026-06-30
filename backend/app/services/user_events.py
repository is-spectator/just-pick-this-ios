from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HelpAnswer, HelpCard, RecommendationCard, UserBehaviorEvent
from app.services.experiments import experiment_assignments_from_payload, merge_experiment_metadata
from app.services.intent_memory import record_intent_answer_feedback_for_card
from app.services.runtime import ensure_user, session_scope
from app.services.user_preferences import serialize_user_preference_memory, update_user_preference_memory_from_event


CORE_USER_EVENT_TYPES = {
    "recommendation_card_accepted",
    "recommendation_card_rejected",
    "recommendation_card_changed",
    "ask_human_requested",
    "help_card_published",
    "help_feed_impression",
    "help_card_skipped",
    "one_liner_submitted",
    "one_liner_reward_granted",
    "one_liner_reward_rejected",
    "final_recommendation_accepted",
    "recommendation_card_post_review_satisfied",
    "recommendation_card_post_review_regretted",
    "recommendation_card_post_review_not_went",
    "recommendation_card_post_review_unknown",
    "favorite_choice_saved",
    "favorite_choice_removed",
    "favorite_choice_restored",
    "favorite_choice_unhidden",
    "drawer_history_pinned",
    "drawer_history_unpinned",
    "drawer_history_hidden",
    "drawer_history_restored",
    "drawer_history_renamed",
}

FAVORITE_ACTIVE_EVENT_TYPES = {
    "favorite_choice_saved",
    "favorite_choice_restored",
    "favorite_choice_unhidden",
}
FAVORITE_REMOVED_EVENT_TYPES = {"favorite_choice_removed"}
FAVORITE_EVENT_TYPES = FAVORITE_ACTIVE_EVENT_TYPES | FAVORITE_REMOVED_EVENT_TYPES
DRAWER_HISTORY_EVENT_TYPES = {
    "drawer_history_pinned",
    "drawer_history_unpinned",
    "drawer_history_hidden",
    "drawer_history_restored",
    "drawer_history_renamed",
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


def get_user_preferences(payload: dict[str, Any]) -> dict[str, Any]:
    device_uid = payload.get("device_uid") or payload.get("device_id")
    user_id = payload.get("user_id")
    if not device_uid and not user_id:
        raise HTTPException(status_code=422, detail="device_uid_or_user_id_required")
    with session_scope() as session:
        user = ensure_user(session, device_uid=device_uid or str(user_id), user_id=user_id)
        return serialize_user_preference_memory(user)


def list_user_favorites(
    *,
    user_id: str | None = None,
    device_uid: str | None = None,
    limit: int = 80,
    cursor: str | None = None,
) -> dict[str, Any]:
    resolved_limit = max(1, min(int(limit or 80), 100))
    # Favorite state is reconstructed from recent behavior events. Fetch a wider
    # window than the display limit so remove/restore events can settle locally.
    event_limit = max(250, resolved_limit * 8)
    try:
        offset = max(0, int(cursor or 0))
    except ValueError:
        offset = 0

    with session_scope() as session:
        user = ensure_user(session, user_id=user_id, device_uid=device_uid)
        events = list(
            session.scalars(
                select(UserBehaviorEvent)
                .where(
                    UserBehaviorEvent.user_id == user.id,
                    UserBehaviorEvent.event_type.in_(sorted(FAVORITE_EVENT_TYPES)),
                )
                .order_by(UserBehaviorEvent.created_at.desc())
                .offset(offset)
                .limit(event_limit)
            )
        )
        states = _favorite_states_from_events(events)
        items = [
            item
            for state in states
            if state["active"] and (item := _serialize_favorite_choice(session, state)) is not None
        ]
        return {"items": items[:resolved_limit], "next_cursor": None}


def get_drawer_history_state(
    *,
    user_id: str | None = None,
    device_uid: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    event_limit = max(1, min(int(limit or 500), 1000))
    with session_scope() as session:
        user = ensure_user(session, user_id=user_id, device_uid=device_uid)
        events = list(
            session.scalars(
                select(UserBehaviorEvent)
                .where(
                    UserBehaviorEvent.user_id == user.id,
                    UserBehaviorEvent.event_type.in_(sorted(DRAWER_HISTORY_EVENT_TYPES)),
                )
                .order_by(UserBehaviorEvent.created_at.asc())
                .limit(event_limit)
            )
        )
        return _drawer_history_state_from_events(events)


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

    card = session.get(RecommendationCard, recommendation_card_id) if recommendation_card_id else None
    context = _resolve_context(
        session,
        user_id=user_id,
        device_uid=str(device_uid) if device_uid else None,
        conversation_id=conversation_id,
        recommendation_card_id=recommendation_card_id,
        help_card_id=help_card_id,
        help_answer_id=help_answer_id,
    )
    event_metadata = _inherit_experiment_metadata(
        session,
        dict(payload_json or {}),
        card=card,
        help_card_id=context.get("help_card_id"),
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
            **event_metadata,
            "known_core_event": normalized_type in CORE_USER_EVENT_TYPES,
        },
    )
    session.add(event)
    record_intent_answer_feedback_for_card(
        session,
        card_id=recommendation_card_id,
        event_type=normalized_type,
        metadata=event.payload_json,
    )
    update_user_preference_memory_from_event(session, event, card=card)
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


def _favorite_states_from_events(events: list[UserBehaviorEvent]) -> list[dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    for event in events:
        metadata = dict(event.payload_json or {})
        key = _favorite_state_key(event, metadata)
        if not key:
            continue
        if key not in states:
            states[key] = {
                "key": key,
                "active": event.event_type in FAVORITE_ACTIVE_EVENT_TYPES,
                "metadata": metadata,
                "created_at": event.created_at,
            }
            continue
        existing = states[key]
        existing["metadata"] = _merge_missing_metadata(existing["metadata"], metadata)
    return list(states.values())


def _favorite_state_key(event: UserBehaviorEvent, metadata: dict[str, Any]) -> str | None:
    for field in ("history_id", "card_id", "recommendation_card_id"):
        value = str(metadata.get(field) or "").strip()
        if value:
            return value
    if event.recommendation_card_id:
        return str(event.recommendation_card_id)
    return None


def _merge_missing_metadata(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary)
    for key, value in fallback.items():
        if key not in merged or merged.get(key) in (None, ""):
            merged[key] = value
    return merged


def _serialize_favorite_choice(session: Session, state: dict[str, Any]) -> dict[str, Any] | None:
    metadata = dict(state.get("metadata") or {})
    card = _favorite_card_from_metadata(session, metadata)
    history_id = str(metadata.get("history_id") or metadata.get("card_id") or state.get("key") or "").strip()
    query = str(metadata.get("query") or _card_query(card) or "").strip()
    title = str(metadata.get("title") or getattr(card, "title", "") or query).strip()
    if not history_id or not (query or title):
        return None
    top_pick = _favorite_top_pick_payload(metadata, card=card, query=query or title)
    return {
        "id": history_id,
        "query": query or title,
        "status": str(metadata.get("status") or "saved"),
        "help_request_id": metadata.get("help_request_id"),
        "top_pick": top_pick,
        "created_at": state.get("created_at"),
    }


def _favorite_card_from_metadata(session: Session, metadata: dict[str, Any]) -> RecommendationCard | None:
    card_id = _lenient_optional_uuid(metadata.get("card_id") or metadata.get("recommendation_card_id"))
    if not card_id:
        return None
    return session.get(RecommendationCard, card_id)


def _favorite_top_pick_payload(
    metadata: dict[str, Any],
    *,
    card: RecommendationCard | None,
    query: str,
) -> dict[str, Any] | None:
    title = str(metadata.get("title") or getattr(card, "title", "") or "").strip()
    if not title:
        return None
    subtitle = str(metadata.get("subtitle") or getattr(card, "subtitle", "") or "").strip()
    reason = str(metadata.get("reason") or getattr(card, "reason", "") or "").strip()
    card_id = str(metadata.get("card_id") or metadata.get("recommendation_card_id") or getattr(card, "id", "") or "").strip()
    return {
        "card_id": card_id or None,
        "query": query,
        "preface": str(metadata.get("preface") or "别查了,就这个。"),
        "title": title,
        "subtitle": subtitle or "保存过的选择",
        "reason": reason or subtitle or "你保存过这个选择，可以继续回看。",
        "bullets": [],
        "warning": "",
        "followups": [],
    }


def _card_query(card: RecommendationCard | None) -> str | None:
    if card is None:
        return None
    metadata = card.payload_json or {}
    for key in ("query", "original_query", "intent_text"):
        value = str(metadata.get(key) or "").strip()
        if value:
            return value
    return card.title


def _drawer_history_state_from_events(events: list[UserBehaviorEvent]) -> dict[str, Any]:
    pinned: set[str] = set()
    hidden: set[str] = set()
    renamed: dict[str, str] = {}
    updated_at = None

    for event in events:
        metadata = dict(event.payload_json or {})
        history_id = str(metadata.get("history_id") or "").strip()
        if not history_id:
            continue
        updated_at = event.created_at
        if event.event_type == "drawer_history_pinned":
            pinned.add(history_id)
            hidden.discard(history_id)
        elif event.event_type == "drawer_history_unpinned":
            pinned.discard(history_id)
        elif event.event_type == "drawer_history_hidden":
            hidden.add(history_id)
            pinned.discard(history_id)
            renamed.pop(history_id, None)
        elif event.event_type == "drawer_history_restored":
            hidden.discard(history_id)
        elif event.event_type == "drawer_history_renamed":
            title = str(metadata.get("title") or "").strip()
            if title:
                renamed[history_id] = title
            else:
                renamed.pop(history_id, None)

    return {
        "pinned_history_ids": sorted(pinned),
        "hidden_history_ids": sorted(hidden),
        "renamed_history_titles": dict(sorted(renamed.items())),
        "updated_at": updated_at,
    }


def _lenient_optional_uuid(value: Any) -> uuid.UUID | None:
    try:
        return _optional_uuid(value)
    except HTTPException:
        return None


def _inherit_experiment_metadata(
    session: Session,
    payload_json: dict[str, Any],
    *,
    card: RecommendationCard | None,
    help_card_id: uuid.UUID | None,
) -> dict[str, Any]:
    if payload_json.get("experiment_assignments"):
        return payload_json
    assignments = experiment_assignments_from_payload(card.payload_json if card is not None else None)
    if not assignments and help_card_id is not None:
        help_card = session.get(HelpCard, help_card_id)
        assignments = experiment_assignments_from_payload(help_card.payload_json if help_card is not None else None)
    if not assignments:
        return payload_json
    return merge_experiment_metadata(payload_json, assignments)


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
