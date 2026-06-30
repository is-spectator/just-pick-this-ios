from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models import RecommendationCard, User, UserBehaviorEvent


PREFERENCE_PROFILE_KEY = "preference_memory_v1"
PREFERENCE_VERSION = "user_preference_memory_v1"

POSITIVE_EVENT_TYPES = {
    "recommendation_card_accepted",
    "final_recommendation_accepted",
}
NEGATIVE_EVENT_TYPES = {
    "recommendation_card_rejected",
    "recommendation_card_changed",
}


def update_user_preference_memory_from_event(
    session: Session,
    event: UserBehaviorEvent,
    *,
    card: RecommendationCard | None = None,
) -> dict[str, Any] | None:
    """Update the user's lightweight preference memory from an explicit event.

    V1 deliberately uses `users.profile_json` instead of a new table. This keeps
    the product path migration-free while still making accepted/rejected
    recommendation behavior available to later personalization work.
    """

    if event.user_id is None:
        return None
    user = session.get(User, event.user_id)
    if user is None:
        return None

    signals = preference_signals_from_event(event, card=card)
    if not signals:
        return _current_memory(user)

    profile = dict(user.profile_json or {})
    memory = dict(profile.get(PREFERENCE_PROFILE_KEY) or {})
    memory.setdefault("version", PREFERENCE_VERSION)
    memory.setdefault("positive_event_count", 0)
    memory.setdefault("negative_event_count", 0)
    memory.setdefault("explicit_signal_count", 0)
    memory.setdefault("counters", {})
    memory.setdefault("recent_event_ids", [])

    event_type = event.event_type
    if event_type in POSITIVE_EVENT_TYPES:
        memory["positive_event_count"] = int(memory.get("positive_event_count") or 0) + 1
    elif event_type in NEGATIVE_EVENT_TYPES:
        memory["negative_event_count"] = int(memory.get("negative_event_count") or 0) + 1

    if signals.get("explicit"):
        memory["explicit_signal_count"] = int(memory.get("explicit_signal_count") or 0) + 1

    counters = dict(memory.get("counters") or {})
    weight = _event_weight(event_type)
    for category, values in signals.items():
        if category == "explicit":
            continue
        bucket = dict(counters.get(category) or {})
        for value in _string_values(values):
            bucket[value] = int(bucket.get(value) or 0) + weight
        counters[category] = {key: value for key, value in sorted(bucket.items()) if value != 0}
    memory["counters"] = counters

    recent_ids = [str(item) for item in memory.get("recent_event_ids") or []]
    event_id = str(event.id) if event.id else None
    if event_id:
        recent_ids = ([event_id] + [item for item in recent_ids if item != event_id])[:20]
    memory["recent_event_ids"] = recent_ids
    memory["summary"] = summarize_preference_memory(memory)
    memory["updated_at"] = datetime.now(timezone.utc).isoformat()

    profile[PREFERENCE_PROFILE_KEY] = memory
    user.profile_json = profile
    session.add(user)
    return memory


def preference_signals_from_event(
    event: UserBehaviorEvent,
    *,
    card: RecommendationCard | None = None,
) -> dict[str, Any]:
    payload = dict(event.payload_json or {})
    signals: dict[str, Any] = {}
    explicit = False

    explicit_fields = {
        "cuisine": "cuisines",
        "food_item": "food_items",
        "taste_preference": "taste_preferences",
        "spice_preference": "spice_preferences",
        "budget_preference": "budget_preferences",
        "companion": "companions",
        "party_type": "companions",
        "area": "areas",
        "city": "cities",
    }
    for source_key, target_key in explicit_fields.items():
        if source_key in payload:
            values = _string_values(payload.get(source_key))
            if values:
                signals[target_key] = [*signals.get(target_key, []), *values]
                explicit = True

    if card is not None:
        card_payload = dict(card.payload_json or {})
        item = card_payload.get("item") if isinstance(card_payload.get("item"), Mapping) else {}
        title = str(item.get("title") or card.title or "").strip()
        category = str(item.get("category") or card_payload.get("target_type") or "").strip()
        if title:
            signals["accepted_items"] = [title]
        if category:
            signals["accepted_categories"] = [category]
        subtitle = str(card.subtitle or "").strip()
        if subtitle:
            for area in ("三里屯", "朝阳区", "望京", "南锣鼓巷", "五道口", "故宫"):
                if area in subtitle:
                    signals["areas"] = [*signals.get("areas", []), area]
        place = card_payload.get("place") if isinstance(card_payload.get("place"), Mapping) else {}
        if place.get("name"):
            signals["accepted_places"] = [str(place["name"])]
        if card_payload.get("target_type"):
            signals["target_types"] = [str(card_payload["target_type"])]

    if explicit:
        signals["explicit"] = True
    return signals


def summarize_preference_memory(memory: Mapping[str, Any]) -> dict[str, Any]:
    counters = memory.get("counters") if isinstance(memory.get("counters"), Mapping) else {}
    return {
        "top_cuisines": _top_values(counters.get("cuisines")),
        "top_food_items": _top_values(counters.get("food_items")),
        "taste_preferences": _top_values(counters.get("taste_preferences")),
        "spice_preferences": _top_values(counters.get("spice_preferences")),
        "budget_preferences": _top_values(counters.get("budget_preferences")),
        "companions": _top_values(counters.get("companions")),
        "areas": _top_values(counters.get("areas")),
        "accepted_items": _top_values(counters.get("accepted_items")),
        "negative_items": _negative_values(counters.get("accepted_items")),
    }


def serialize_user_preference_memory(user: User) -> dict[str, Any]:
    profile = dict(user.profile_json or {})
    memory = dict(profile.get(PREFERENCE_PROFILE_KEY) or {})
    if not memory:
        memory = {
            "version": PREFERENCE_VERSION,
            "positive_event_count": 0,
            "negative_event_count": 0,
            "explicit_signal_count": 0,
            "counters": {},
            "summary": {},
        }
    return {
        "user_id": str(user.id),
        "device_uid": user.device_uid,
        "preference_memory": memory,
    }


def _current_memory(user: User) -> dict[str, Any] | None:
    profile = dict(user.profile_json or {})
    value = profile.get(PREFERENCE_PROFILE_KEY)
    return dict(value) if isinstance(value, Mapping) else None


def _event_weight(event_type: str) -> int:
    if event_type in POSITIVE_EVENT_TYPES:
        return 2
    if event_type in NEGATIVE_EVENT_TYPES:
        return -2
    return 1


def _string_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = [value]
    cleaned: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _top_values(value: Any, *, limit: int = 5) -> list[dict[str, Any]]:
    if not isinstance(value, Mapping):
        return []
    ranked = sorted(
        (
            {"value": str(key), "score": int(score)}
            for key, score in value.items()
            if int(score) > 0
        ),
        key=lambda item: (-item["score"], item["value"]),
    )
    return ranked[:limit]


def _negative_values(value: Any, *, limit: int = 5) -> list[dict[str, Any]]:
    if not isinstance(value, Mapping):
        return []
    ranked = sorted(
        (
            {"value": str(key), "score": int(score)}
            for key, score in value.items()
            if int(score) < 0
        ),
        key=lambda item: (item["score"], item["value"]),
    )
    return ranked[:limit]


__all__ = [
    "PREFERENCE_PROFILE_KEY",
    "PREFERENCE_VERSION",
    "preference_signals_from_event",
    "serialize_user_preference_memory",
    "summarize_preference_memory",
    "update_user_preference_memory_from_event",
]
