from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException

from app.models import RecommendationCard
from app.services.experiments import experiment_assignments_from_payload, merge_experiment_metadata
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
            payload_json=_card_feedback_metadata(
                card,
                {
                    "status": "completed",
                    "already_accepted": already_accepted,
                    **dict(payload.get("metadata") or {}),
                },
            ),
        )
        session.flush()
        return {"card_id": str(card.id), "accepted": True, "metadata": {"status": "completed"}}


def reject_card(id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return _feedback_card(
        id,
        payload,
        event_type="recommendation_card_rejected",
        status="rejected",
        action="reject",
    )


def change_card(id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return _feedback_card(
        id,
        payload,
        event_type="recommendation_card_changed",
        status="changed",
        action="change",
    )


def ask_human_for_card(id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return _feedback_card(
        id,
        payload,
        event_type="ask_human_requested",
        status="asked_human",
        action="ask_human",
    )


def review_card(id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    outcome = _post_review_outcome(payload)
    event_type = {
        "went_satisfied": "recommendation_card_post_review_satisfied",
        "went_regretted": "recommendation_card_post_review_regretted",
        "not_went": "recommendation_card_post_review_not_went",
        "unknown": "recommendation_card_post_review_unknown",
    }[outcome]
    status = {
        "went_satisfied": "reviewed_satisfied",
        "went_regretted": "reviewed_regretted",
        "not_went": "reviewed_not_went",
        "unknown": "reviewed_unknown",
    }[outcome]
    return _feedback_card(
        id,
        {
            **payload,
            "metadata": {
                "outcome": outcome,
                "went": outcome != "not_went" if outcome != "unknown" else payload.get("went"),
                "satisfied": outcome == "went_satisfied" if outcome != "unknown" else payload.get("satisfied"),
                "notes": payload.get("notes"),
                **dict(payload.get("metadata") or {}),
            },
        },
        event_type=event_type,
        status=status,
        action="post_review",
    )


def _feedback_card(
    id: str,
    payload: dict[str, Any] | None,
    *,
    event_type: str,
    status: str,
    action: str,
) -> dict[str, Any]:
    payload = payload or {}
    with session_scope() as session:
        card = session.get(RecommendationCard, uuid.UUID(id))
        if card is None:
            raise HTTPException(status_code=404, detail="card_not_found")
        previous_status = card.status
        card.status = status
        metadata = {
            "action": action,
            "status": status,
            "previous_status": previous_status,
            "reason": payload.get("reason"),
            "tags": [str(item).strip() for item in payload.get("tags") or [] if str(item).strip()],
            **dict(payload.get("metadata") or {}),
        }
        metadata = _card_feedback_metadata(card, metadata)
        event = record_user_behavior_event(
            session,
            event_type=event_type,
            user_id=_optional_uuid(payload.get("user_id")) or card.user_id,
            device_uid=payload.get("device_uid") or payload.get("device_id"),
            conversation_id=card.conversation_id,
            recommendation_card_id=card.id,
            source="api",
            payload_json=metadata,
        )
        session.flush()
        return {
            "card_id": str(card.id),
            "accepted": event_type == "recommendation_card_post_review_satisfied",
            "feedback": {
                "action": action,
                "status": status,
                "previous_status": previous_status,
                "outcome": metadata.get("outcome"),
            },
            "event": {
                "id": str(event.id),
                "event_type": event.event_type,
            },
            "metadata": {"status": status},
        }


def _optional_uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def _card_feedback_metadata(card: RecommendationCard, payload: dict[str, Any]) -> dict[str, Any]:
    assignments = experiment_assignments_from_payload(card.payload_json or {})
    return merge_experiment_metadata(payload, assignments)


def _post_review_outcome(payload: dict[str, Any]) -> str:
    outcome = str(payload.get("outcome") or "").strip()
    if outcome in {"went_satisfied", "went_regretted", "not_went", "unknown"}:
        return outcome
    went = payload.get("went")
    satisfied = payload.get("satisfied")
    if went is False:
        return "not_went"
    if went is True and satisfied is True:
        return "went_satisfied"
    if went is True and satisfied is False:
        return "went_regretted"
    return "unknown"
