from __future__ import annotations

from types import SimpleNamespace

from app.services.personalization_metrics import personalization_summary_from_records


def _card(id: str, payload_json: dict[str, object] | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=id, payload_json=payload_json or {})


def _accepted_event(card_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        event_type="recommendation_card_accepted",
        recommendation_card_id=card_id,
    )


def test_personalization_summary_compares_acceptance_lift() -> None:
    summary = personalization_summary_from_records(
        cards=[
            _card("personalized-query", {"preference_source": "query"}),
            _card("personalized-memory", {"metadata": {"personalization": {"source": "user_memory"}}}),
            _card("baseline-a"),
            _card("baseline-b"),
        ],
        events=[
            _accepted_event("personalized-query"),
            _accepted_event("personalized-memory"),
            _accepted_event("baseline-a"),
            _accepted_event("unknown-card"),
        ],
        window_hours=24,
    )

    assert summary["counts"] == {
        "recommendation_card_shown": 4,
        "personalized_card_count": 2,
        "baseline_card_count": 2,
        "personalized_accepted_count": 2,
        "baseline_accepted_count": 1,
        "accepted_card_count": 3,
    }
    assert summary["rates"] == {
        "preference_hit_rate": 0.5,
        "personalized_acceptance_rate": 1.0,
        "baseline_acceptance_rate": 0.5,
        "personalized_acceptance_lift": 0.5,
    }
    assert summary["personalization_sources"] == {"query": 1, "user_memory": 1}
    assert summary["metadata"]["version"] == "personalization_summary_v1"


def test_personalization_summary_handles_empty_denominators() -> None:
    summary = personalization_summary_from_records(cards=[], events=[])

    assert summary["counts"]["recommendation_card_shown"] == 0
    assert summary["rates"]["preference_hit_rate"] is None
    assert summary["rates"]["personalized_acceptance_rate"] is None
    assert summary["rates"]["baseline_acceptance_rate"] is None
    assert summary["rates"]["personalized_acceptance_lift"] is None
