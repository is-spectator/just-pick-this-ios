from __future__ import annotations

from types import SimpleNamespace

from app.services.user_preferences import preference_signals_from_event, summarize_preference_memory


def test_preference_signals_extract_explicit_metadata() -> None:
    event = SimpleNamespace(
        event_type="ask_human_requested",
        payload_json={
            "cuisine": "粤菜",
            "taste_preference": ["清淡", "安静"],
            "spice_preference": "not_spicy",
            "budget_preference": "budget_low",
            "companion": "parents",
            "area": "望京",
        },
    )

    signals = preference_signals_from_event(event)

    assert signals["explicit"] is True
    assert signals["cuisines"] == ["粤菜"]
    assert signals["taste_preferences"] == ["清淡", "安静"]
    assert signals["spice_preferences"] == ["not_spicy"]
    assert signals["budget_preferences"] == ["budget_low"]
    assert signals["companions"] == ["parents"]
    assert signals["areas"] == ["望京"]


def test_preference_signals_extract_card_context() -> None:
    event = SimpleNamespace(event_type="recommendation_card_accepted", payload_json={})
    card = SimpleNamespace(
        title="番茄锅 + 牛肉/虾滑 + 蔬菜",
        subtitle="海底捞 · 默认 2 人",
        payload_json={
            "target_type": "ordering_bundle",
            "item": {
                "title": "番茄锅 + 牛肉/虾滑 + 蔬菜",
                "category": "火锅",
            },
            "place": {"name": "海底捞"},
        },
    )

    signals = preference_signals_from_event(event, card=card)

    assert signals["accepted_items"] == ["番茄锅 + 牛肉/虾滑 + 蔬菜"]
    assert signals["accepted_categories"] == ["火锅"]
    assert signals["accepted_places"] == ["海底捞"]
    assert signals["target_types"] == ["ordering_bundle"]


def test_summarize_preference_memory_ranks_positive_and_negative_values() -> None:
    summary = summarize_preference_memory(
        {
            "counters": {
                "cuisines": {"粤菜": 3, "湘菜": -2, "杭帮菜": 1},
                "taste_preferences": {"清淡": 4},
                "spice_preferences": {"not_spicy": 2},
                "accepted_items": {"热干面": 2, "重辣火锅": -2},
            }
        }
    )

    assert summary["top_cuisines"][0] == {"value": "粤菜", "score": 3}
    assert summary["taste_preferences"] == [{"value": "清淡", "score": 4}]
    assert summary["spice_preferences"] == [{"value": "not_spicy", "score": 2}]
    assert summary["negative_items"] == [{"value": "重辣火锅", "score": -2}]
