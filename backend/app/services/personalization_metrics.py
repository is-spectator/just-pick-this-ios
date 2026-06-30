"""Metrics for measuring whether personalization improves recommendation acceptance."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RecommendationCard, UserBehaviorEvent


ACCEPT_EVENT_TYPES = {"recommendation_card_accepted", "final_recommendation_accepted"}


def personalization_summary(
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
        .where(UserBehaviorEvent.created_at >= start)
        .order_by(UserBehaviorEvent.created_at.asc())
    ).all()
    return personalization_summary_from_records(cards=cards, events=events, window_start=start, window_hours=since_hours)


def personalization_summary_from_records(
    *,
    cards: list[Any],
    events: list[Any],
    window_start: datetime | None = None,
    window_hours: int | None = None,
) -> dict[str, Any]:
    card_ids = {_record_id(card) for card in cards if _record_id(card)}
    personalized_ids = {_record_id(card) for card in cards if _record_id(card) and _is_personalized_card(card)}
    personalized_ids.discard(None)
    baseline_ids = card_ids - personalized_ids
    accepted_ids = {
        _event_card_id(event)
        for event in events
        if str(getattr(event, "event_type", "") or "") in ACCEPT_EVENT_TYPES and _event_card_id(event) in card_ids
    }
    accepted_ids.discard(None)

    personalized_accepted = len(personalized_ids.intersection(accepted_ids))
    baseline_accepted = len(baseline_ids.intersection(accepted_ids))
    personalized_rate = _rate(personalized_accepted, len(personalized_ids))
    baseline_rate = _rate(baseline_accepted, len(baseline_ids))
    lift = _lift(personalized_rate, baseline_rate)
    return {
        "window_start": window_start.isoformat() if window_start else None,
        "window_hours": window_hours,
        "counts": {
            "recommendation_card_shown": len(card_ids),
            "personalized_card_count": len(personalized_ids),
            "baseline_card_count": len(baseline_ids),
            "personalized_accepted_count": personalized_accepted,
            "baseline_accepted_count": baseline_accepted,
            "accepted_card_count": len(accepted_ids),
        },
        "rates": {
            "preference_hit_rate": _rate(len(personalized_ids), len(card_ids)),
            "personalized_acceptance_rate": personalized_rate,
            "baseline_acceptance_rate": baseline_rate,
            "personalized_acceptance_lift": lift,
        },
        "personalization_sources": _source_counts(cards),
        "metadata": {
            "version": "personalization_summary_v1",
            "accept_event_types": sorted(ACCEPT_EVENT_TYPES),
            "contract": "compare acceptance for cards with preference metadata against baseline cards",
        },
    }


def _is_personalized_card(card: Any) -> bool:
    payload = dict(getattr(card, "payload_json", None) or {})
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    if payload.get("preference_rule_name") or payload.get("preference_source"):
        return True
    if payload.get("area_food_preference") or metadata.get("area_food_preference"):
        return True
    if payload.get("personalization") or metadata.get("personalization"):
        return True
    provenance = payload.get("provenance") if isinstance(payload.get("provenance"), dict) else {}
    return bool(provenance.get("preference_rule_name") or provenance.get("preference_source"))


def _source_counts(cards: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for card in cards:
        if not _is_personalized_card(card):
            continue
        payload = dict(getattr(card, "payload_json", None) or {})
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        provenance = payload.get("provenance") if isinstance(payload.get("provenance"), dict) else {}
        personalization = (
            payload.get("personalization")
            if isinstance(payload.get("personalization"), dict)
            else metadata.get("personalization")
            if isinstance(metadata.get("personalization"), dict)
            else {}
        )
        source = (
            payload.get("preference_source")
            or metadata.get("preference_source")
            or provenance.get("preference_source")
            or personalization.get("source")
            or "unknown"
        )
        key = str(source or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


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


def _lift(personalized_rate: float | None, baseline_rate: float | None) -> float | None:
    if personalized_rate is None or baseline_rate is None:
        return None
    return round(personalized_rate - baseline_rate, 4)


__all__ = ["personalization_summary", "personalization_summary_from_records"]
