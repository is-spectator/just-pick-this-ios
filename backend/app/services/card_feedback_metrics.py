"""Operational metrics for recommendation-card feedback actions."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RecommendationCard, UserBehaviorEvent


POSITIVE_FEEDBACK_EVENT_TYPES = {
    "recommendation_card_accepted",
    "final_recommendation_accepted",
    "recommendation_card_post_review_satisfied",
}
NEGATIVE_FEEDBACK_EVENT_TYPES = {
    "recommendation_card_rejected",
    "recommendation_card_changed",
    "ask_human_requested",
    "recommendation_card_post_review_regretted",
    "recommendation_card_post_review_not_went",
}
NEUTRAL_FEEDBACK_EVENT_TYPES = {
    "recommendation_card_post_review_unknown",
}
CARD_FEEDBACK_EVENT_TYPES = (
    POSITIVE_FEEDBACK_EVENT_TYPES | NEGATIVE_FEEDBACK_EVENT_TYPES | NEUTRAL_FEEDBACK_EVENT_TYPES
)


def card_feedback_summary(
    session: Session,
    *,
    since_hours: int = 24 * 30,
) -> dict[str, Any]:
    start = datetime.now(timezone.utc) - timedelta(hours=max(1, int(since_hours or 1)))
    cards = session.scalars(
        select(RecommendationCard)
        .where(RecommendationCard.created_at >= start)
        .order_by(RecommendationCard.created_at.asc())
    ).all()
    events = session.scalars(
        select(UserBehaviorEvent)
        .where(
            UserBehaviorEvent.event_type.in_(sorted(CARD_FEEDBACK_EVENT_TYPES)),
            UserBehaviorEvent.created_at >= start,
        )
        .order_by(UserBehaviorEvent.created_at.asc())
    ).all()
    return card_feedback_summary_from_records(cards=cards, events=events, window_start=start, window_hours=since_hours)


def card_feedback_summary_from_records(
    *,
    cards: list[Any],
    events: list[Any],
    window_start: datetime | None = None,
    window_hours: int | None = None,
) -> dict[str, Any]:
    card_ids = {_record_id(card) for card in cards if _record_id(card)}
    card_by_id = {_record_id(card): card for card in cards if _record_id(card)}
    feedback_events = [
        event
        for event in events
        if str(getattr(event, "event_type", "") or "") in CARD_FEEDBACK_EVENT_TYPES
        and _event_card_id(event) in card_ids
    ]
    feedback_card_ids = {_event_card_id(event) for event in feedback_events if _event_card_id(event)}
    positive_card_ids = {
        _event_card_id(event)
        for event in feedback_events
        if str(getattr(event, "event_type", "") or "") in POSITIVE_FEEDBACK_EVENT_TYPES
    }
    negative_card_ids = {
        _event_card_id(event)
        for event in feedback_events
        if str(getattr(event, "event_type", "") or "") in NEGATIVE_FEEDBACK_EVENT_TYPES
    }
    neutral_card_ids = {
        _event_card_id(event)
        for event in feedback_events
        if str(getattr(event, "event_type", "") or "") in NEUTRAL_FEEDBACK_EVENT_TYPES
    }
    feedback_card_ids.discard(None)
    positive_card_ids.discard(None)
    negative_card_ids.discard(None)
    neutral_card_ids.discard(None)

    event_counts = Counter(str(getattr(event, "event_type", "") or "") for event in feedback_events)
    linked_event_count = sum(
        1
        for event in feedback_events
        if _intent_answer_id_from_event_or_card(event, card_by_id.get(_event_card_id(event))) is not None
    )
    return {
        "window_start": window_start.isoformat() if window_start else None,
        "window_hours": window_hours,
        "counts": {
            "recommendation_card_shown": len(card_ids),
            "feedback_event_count": len(feedback_events),
            "feedback_card_count": len(feedback_card_ids),
            "positive_feedback_card_count": len(positive_card_ids),
            "negative_feedback_card_count": len(negative_card_ids),
            "neutral_feedback_card_count": len(neutral_card_ids),
            "intent_answer_linked_feedback_event_count": linked_event_count,
        },
        "rates": {
            "feedback_rate": _rate(len(feedback_card_ids), len(card_ids)),
            "positive_feedback_rate": _rate(len(positive_card_ids), len(card_ids)),
            "negative_feedback_rate": _rate(len(negative_card_ids), len(card_ids)),
            "negative_feedback_share": _rate(len(negative_card_ids), len(feedback_card_ids)),
            "intent_answer_feedback_link_rate": _rate(linked_event_count, len(feedback_events)),
        },
        "event_counts": dict(sorted(event_counts.items())),
        "core_feedback_event_coverage": {
            event_type: event_counts.get(event_type, 0) > 0
            for event_type in sorted(CARD_FEEDBACK_EVENT_TYPES)
        },
        "metadata": {
            "version": "card_feedback_summary_v1",
            "positive_event_types": sorted(POSITIVE_FEEDBACK_EVENT_TYPES),
            "negative_event_types": sorted(NEGATIVE_FEEDBACK_EVENT_TYPES),
            "neutral_event_types": sorted(NEUTRAL_FEEDBACK_EVENT_TYPES),
            "contract": "measure recommendation-card feedback actions and intent-answer linkage",
        },
    }


def _intent_answer_id_from_event_or_card(event: Any, card: Any | None) -> str | None:
    event_payload = getattr(event, "payload_json", None)
    for payload in (event_payload, getattr(card, "payload_json", None) if card is not None else None):
        if not isinstance(payload, dict):
            continue
        direct = payload.get("intent_answer_id") or payload.get("reference_intent_answer_id")
        if direct:
            return str(direct)
        provenance = payload.get("provenance")
        if isinstance(provenance, dict):
            source_answer_id = provenance.get("source_answer_id")
            source_answer_type = str(provenance.get("source_answer_type") or "")
            if source_answer_id and source_answer_type in {"intent_answer", "area_intent_answer", "ordering_bundle_answer"}:
                return str(source_answer_id)
    return None


def _record_id(record: Any) -> str | None:
    value = getattr(record, "id", None)
    return str(value) if value is not None else None


def _event_card_id(event: Any) -> str | None:
    value = getattr(event, "recommendation_card_id", None)
    return str(value) if value is not None else None


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


__all__ = [
    "CARD_FEEDBACK_EVENT_TYPES",
    "NEGATIVE_FEEDBACK_EVENT_TYPES",
    "POSITIVE_FEEDBACK_EVENT_TYPES",
    "card_feedback_summary",
    "card_feedback_summary_from_records",
]
