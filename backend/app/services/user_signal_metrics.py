from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HelpCard, RecommendationCard, UserBehaviorEvent

FOLLOWUP_EVENT_TYPES = {
    "recommendation_card_rejected",
    "recommendation_card_changed",
    "ask_human_requested",
}
CORE_SIGNAL_EVENT_TYPES = {
    "recommendation_card_accepted",
    *FOLLOWUP_EVENT_TYPES,
    "help_card_published",
    "help_feed_impression",
    "one_liner_submitted",
    "one_liner_reward_granted",
    "one_liner_reward_rejected",
    "final_recommendation_accepted",
}


def user_signal_summary(
    session: Session,
    *,
    since_hours: int = 24 * 30,
) -> dict[str, Any]:
    start = datetime.now(timezone.utc) - timedelta(hours=max(1, int(since_hours or 1)))
    recommendation_cards = session.scalars(
        select(RecommendationCard)
        .where(RecommendationCard.created_at >= start)
        .order_by(RecommendationCard.created_at.asc())
    ).all()
    help_cards = session.scalars(
        select(HelpCard).where(HelpCard.created_at >= start).order_by(HelpCard.created_at.asc())
    ).all()
    events = session.scalars(
        select(UserBehaviorEvent)
        .where(UserBehaviorEvent.created_at >= start)
        .order_by(UserBehaviorEvent.created_at.asc())
    ).all()
    return user_signal_summary_from_records(
        recommendation_cards=recommendation_cards,
        help_cards=help_cards,
        events=events,
        window_start=start,
        window_hours=since_hours,
    )


def user_signal_summary_from_records(
    *,
    recommendation_cards: list[Any],
    help_cards: list[Any],
    events: list[Any],
    window_start: datetime | None = None,
    window_hours: int | None = None,
) -> dict[str, Any]:
    recommendation_card_ids = {_record_id(card) for card in recommendation_cards if _record_id(card) is not None}
    help_card_ids = {_record_id(card) for card in help_cards if _record_id(card) is not None}
    event_counts = {event_type: 0 for event_type in sorted(CORE_SIGNAL_EVENT_TYPES)}
    accepted_card_ids: set[str] = set()
    followup_card_ids: set[str] = set()
    published_help_card_ids: set[str] = set()
    help_feed_impression_pairs: set[tuple[str, str]] = set()
    one_liner_submitted_pairs: set[tuple[str, str]] = set()

    for event in events:
        event_type = str(getattr(event, "event_type", "") or "")
        if event_type in event_counts:
            event_counts[event_type] += 1
        card_id = _event_recommendation_card_id(event)
        help_card_id = _event_help_card_id(event)
        if event_type == "recommendation_card_accepted" and card_id is not None:
            accepted_card_ids.add(card_id)
        if event_type in FOLLOWUP_EVENT_TYPES and card_id is not None:
            followup_card_ids.add(card_id)
        if event_type == "help_card_published" and help_card_id is not None:
            published_help_card_ids.add(help_card_id)
        pair = _user_help_pair(event)
        if event_type == "help_feed_impression" and pair is not None:
            help_feed_impression_pairs.add(pair)
        if event_type == "one_liner_submitted" and pair is not None:
            one_liner_submitted_pairs.add(pair)

    recommendation_shown = len(recommendation_card_ids)
    help_draft_shown = len(help_card_ids)
    return {
        "window_start": window_start.isoformat() if window_start else None,
        "window_hours": window_hours,
        "counts": {
            "recommendation_card_shown": recommendation_shown,
            "accepted_recommendation_cards": len(accepted_card_ids),
            "followup_recommendation_cards": len(followup_card_ids),
            "help_card_draft_shown": help_draft_shown,
            "help_card_published": len(published_help_card_ids),
            "help_feed_impression_pairs": len(help_feed_impression_pairs),
            "one_liner_submitted_pairs": len(one_liner_submitted_pairs),
            "events": event_counts,
        },
        "rates": {
            "accepted_card_rate": _rate(len(accepted_card_ids), recommendation_shown),
            "followup_rate": _rate(len(followup_card_ids), recommendation_shown),
            "help_publish_rate": _rate(len(published_help_card_ids), help_draft_shown),
            "one_liner_submit_rate": _rate(len(one_liner_submitted_pairs), len(help_feed_impression_pairs)),
        },
        "core_event_coverage": {
            event_type: event_counts[event_type] > 0 for event_type in sorted(CORE_SIGNAL_EVENT_TYPES)
        },
        "metadata": {
            "version": "user_signal_summary_v1",
            "followup_event_types": sorted(FOLLOWUP_EVENT_TYPES),
        },
    }


def _record_id(record: Any) -> str | None:
    value = getattr(record, "id", None)
    return str(value) if value is not None else None


def _event_recommendation_card_id(event: Any) -> str | None:
    value = getattr(event, "recommendation_card_id", None)
    return str(value) if value is not None else None


def _event_help_card_id(event: Any) -> str | None:
    value = getattr(event, "help_card_id", None)
    return str(value) if value is not None else None


def _user_help_pair(event: Any) -> tuple[str, str] | None:
    user_id = getattr(event, "user_id", None)
    help_card_id = getattr(event, "help_card_id", None)
    if user_id is None or help_card_id is None:
        return None
    return (str(user_id), str(help_card_id))


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)
