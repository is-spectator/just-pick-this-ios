from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.models import IntentAnswer, RecommendationCard
from app.services.runtime import utcnow


IntentFeedbackOutcome = Literal["success", "rejection"]

SUCCESS_EVENT_TYPES = {
    "recommendation_card_accepted",
    "final_recommendation_accepted",
    "recommendation_card_post_review_satisfied",
}
REJECTION_EVENT_TYPES = {
    "recommendation_card_rejected",
    "recommendation_card_changed",
    "recommendation_card_post_review_regretted",
    "recommendation_card_post_review_not_went",
}


def record_intent_answer_feedback_for_card(
    session: Session,
    *,
    card_id: uuid.UUID | None,
    event_type: str,
    metadata: dict[str, Any] | None = None,
) -> IntentAnswer | None:
    if card_id is None:
        return None
    card = session.get(RecommendationCard, card_id)
    if card is None:
        return None

    normalized_event = str(event_type or "").strip()
    outcome: IntentFeedbackOutcome | None
    if normalized_event in SUCCESS_EVENT_TYPES:
        outcome = "success"
    elif normalized_event in REJECTION_EVENT_TYPES:
        outcome = "rejection"
    else:
        return None

    payload = dict(metadata or {})
    if payload.get("already_accepted") and outcome == "success":
        return None

    answer = resolve_card_intent_answer(session, card)
    if answer is None:
        return None

    if outcome == "success":
        answer.success_count = int(answer.success_count or 0) + 1
        answer.last_used_at = utcnow()
    else:
        answer.rejection_count = int(answer.rejection_count or 0) + 1
    return answer


def resolve_card_intent_answer(session: Session, card: RecommendationCard) -> IntentAnswer | None:
    payload = dict(card.payload_json or {})
    provenance = payload.get("provenance")
    provenance_map = provenance if isinstance(provenance, dict) else {}
    for value in (
        payload.get("intent_answer_id"),
        payload.get("reference_intent_answer_id"),
        provenance_map.get("source_answer_id"),
    ):
        answer_id = _optional_uuid(value)
        if answer_id is None:
            continue
        answer = session.get(IntentAnswer, answer_id)
        if answer is not None:
            return answer
    return None


def _optional_uuid(value: Any) -> uuid.UUID | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return uuid.UUID(text)
    except ValueError:
        return None


__all__ = [
    "REJECTION_EVENT_TYPES",
    "SUCCESS_EVENT_TYPES",
    "record_intent_answer_feedback_for_card",
    "resolve_card_intent_answer",
]
