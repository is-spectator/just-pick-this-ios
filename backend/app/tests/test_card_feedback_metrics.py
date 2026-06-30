from __future__ import annotations

from types import SimpleNamespace

from app.services.card_feedback_metrics import card_feedback_summary_from_records


def _card(id: str, payload_json: dict[str, object] | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=id, payload_json=payload_json or {})


def _event(event_type: str, card_id: str, payload_json: dict[str, object] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        event_type=event_type,
        recommendation_card_id=card_id,
        payload_json=payload_json or {},
    )


def test_card_feedback_summary_tracks_feedback_and_negative_rates() -> None:
    summary = card_feedback_summary_from_records(
        cards=[
            _card("card-accept", {"reference_intent_answer_id": "intent-answer-1"}),
            _card("card-reject"),
            _card("card-change"),
            _card("card-ask-human"),
            _card("card-no-feedback"),
        ],
        events=[
            _event("recommendation_card_accepted", "card-accept"),
            _event("recommendation_card_rejected", "card-reject"),
            _event("recommendation_card_changed", "card-change"),
            _event("ask_human_requested", "card-ask-human"),
            _event("recommendation_card_post_review_regretted", "card-accept"),
            _event("recommendation_card_rejected", "unknown-card"),
        ],
        window_hours=24,
    )

    assert summary["counts"] == {
        "recommendation_card_shown": 5,
        "feedback_event_count": 5,
        "feedback_card_count": 4,
        "positive_feedback_card_count": 1,
        "negative_feedback_card_count": 4,
        "neutral_feedback_card_count": 0,
        "intent_answer_linked_feedback_event_count": 2,
    }
    assert summary["rates"] == {
        "feedback_rate": 0.8,
        "positive_feedback_rate": 0.2,
        "negative_feedback_rate": 0.8,
        "negative_feedback_share": 1.0,
        "intent_answer_feedback_link_rate": 0.4,
    }
    assert summary["event_counts"]["recommendation_card_accepted"] == 1
    assert summary["event_counts"]["recommendation_card_rejected"] == 1
    assert summary["event_counts"]["recommendation_card_changed"] == 1
    assert summary["event_counts"]["ask_human_requested"] == 1
    assert summary["event_counts"]["recommendation_card_post_review_regretted"] == 1
    assert summary["core_feedback_event_coverage"]["recommendation_card_accepted"] is True
    assert summary["core_feedback_event_coverage"]["recommendation_card_post_review_satisfied"] is False


def test_card_feedback_summary_handles_empty_denominators() -> None:
    summary = card_feedback_summary_from_records(cards=[], events=[])

    assert summary["counts"]["recommendation_card_shown"] == 0
    assert summary["rates"]["feedback_rate"] is None
    assert summary["rates"]["negative_feedback_rate"] is None
    assert summary["rates"]["negative_feedback_share"] is None
    assert summary["rates"]["intent_answer_feedback_link_rate"] is None
