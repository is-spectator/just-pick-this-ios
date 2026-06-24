from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RecommendationCard, UserBehaviorEvent
from app.services.experiments import experiment_assignments_from_payload, merge_experiment_metadata
from app.services.runtime import serialize_card_detail, session_scope, utcnow
from app.services.user_events import record_user_behavior_event

POST_REVIEW_EVENT_TYPES = {
    "recommendation_card_post_review_satisfied": "went_satisfied",
    "recommendation_card_post_review_regretted": "went_regretted",
    "recommendation_card_post_review_not_went": "not_went",
    "recommendation_card_post_review_unknown": "unknown",
}


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


def post_experience_review_summary(
    session: Session,
    *,
    since_hours: int = 24 * 30,
) -> dict[str, Any]:
    start = datetime.now(timezone.utc) - timedelta(hours=max(1, int(since_hours or 1)))
    events = session.scalars(
        select(UserBehaviorEvent)
        .where(
            UserBehaviorEvent.event_type.in_(
                [
                    "recommendation_card_accepted",
                    *POST_REVIEW_EVENT_TYPES.keys(),
                ]
            ),
            UserBehaviorEvent.created_at >= start,
        )
        .order_by(UserBehaviorEvent.created_at.asc())
    ).all()
    return post_experience_review_summary_from_events(events, window_start=start, window_hours=since_hours)


def post_experience_review_summary_from_events(
    events: list[Any],
    *,
    window_start: datetime | None = None,
    window_hours: int | None = None,
) -> dict[str, Any]:
    accepted_cards: set[str] = set()
    latest_review_by_card: dict[str, str] = {}
    for event in events:
        card_id = _event_card_id(event)
        if card_id is None:
            continue
        event_type = str(getattr(event, "event_type", "") or "")
        if event_type == "recommendation_card_accepted":
            accepted_cards.add(card_id)
            continue
        outcome = _post_review_event_outcome(event)
        if outcome is not None:
            latest_review_by_card[card_id] = outcome

    outcome_counts = {outcome: 0 for outcome in ("went_satisfied", "went_regretted", "not_went", "unknown")}
    for outcome in latest_review_by_card.values():
        outcome_counts[outcome] += 1

    reviewed_count = len(latest_review_by_card)
    accepted_count = len(accepted_cards)
    went_count = outcome_counts["went_satisfied"] + outcome_counts["went_regretted"]
    regret_rate = outcome_counts["went_regretted"] / went_count if went_count else None
    post_review_rate = reviewed_count / accepted_count if accepted_count else None
    not_went_rate = outcome_counts["not_went"] / reviewed_count if reviewed_count else None
    return {
        "window_start": window_start.isoformat() if window_start else None,
        "window_hours": window_hours,
        "accepted_card_count": accepted_count,
        "post_review_count": reviewed_count,
        "post_review_rate": round(post_review_rate, 4) if post_review_rate is not None else None,
        "regret_rate": round(regret_rate, 4) if regret_rate is not None else None,
        "not_went_rate": round(not_went_rate, 4) if not_went_rate is not None else None,
        "outcome_counts": outcome_counts,
        "reviewed_after_acceptance_count": len(set(latest_review_by_card) & accepted_cards),
        "unaccepted_review_count": len(set(latest_review_by_card) - accepted_cards),
        "metrics": {
            "post_review_rate": "post_review_count / recommendation_card_accepted",
            "regret_rate": "went_regretted / (went_satisfied + went_regretted)",
        },
    }


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


def _event_card_id(event: Any) -> str | None:
    card_id = getattr(event, "recommendation_card_id", None)
    if card_id is None:
        return None
    return str(card_id)


def _post_review_event_outcome(event: Any) -> str | None:
    event_type = str(getattr(event, "event_type", "") or "")
    if event_type in POST_REVIEW_EVENT_TYPES:
        return POST_REVIEW_EVENT_TYPES[event_type]
    payload = getattr(event, "payload_json", None)
    if isinstance(payload, Mapping):
        outcome = str(payload.get("outcome") or "").strip()
        if outcome in {"went_satisfied", "went_regretted", "not_went", "unknown"}:
            return outcome
    return None
