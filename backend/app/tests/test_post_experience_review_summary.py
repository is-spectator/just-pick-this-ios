from __future__ import annotations

from types import SimpleNamespace

from app.services.cards import post_experience_review_summary_from_events


def _event(
    event_type: str,
    *,
    card_id: str,
    outcome: str | None = None,
) -> SimpleNamespace:
    payload_json = {}
    if outcome is not None:
        payload_json["outcome"] = outcome
    return SimpleNamespace(
        event_type=event_type,
        recommendation_card_id=card_id,
        payload_json=payload_json,
    )


def test_post_experience_summary_tracks_review_and_regret_rates() -> None:
    events = [
        _event("recommendation_card_accepted", card_id="card-1"),
        _event("recommendation_card_accepted", card_id="card-2"),
        _event("recommendation_card_accepted", card_id="card-3"),
        _event("recommendation_card_accepted", card_id="card-4"),
        _event("recommendation_card_post_review_satisfied", card_id="card-1"),
        _event("recommendation_card_post_review_regretted", card_id="card-2"),
        _event("recommendation_card_post_review_not_went", card_id="card-3"),
    ]

    summary = post_experience_review_summary_from_events(events, window_hours=24)

    assert summary["accepted_card_count"] == 4
    assert summary["post_review_count"] == 3
    assert summary["post_review_rate"] == 0.75
    assert summary["regret_rate"] == 0.5
    assert summary["satisfaction_rate"] == 0.5
    assert summary["not_went_rate"] == 0.3333
    assert summary["reviewed_after_acceptance_rate"] == 1.0
    assert summary["outcome_counts"] == {
        "went_satisfied": 1,
        "went_regretted": 1,
        "not_went": 1,
        "unknown": 0,
    }


def test_post_experience_summary_uses_latest_review_per_card() -> None:
    events = [
        _event("recommendation_card_accepted", card_id="card-1"),
        _event("recommendation_card_post_review_unknown", card_id="card-1"),
        _event("recommendation_card_post_review_satisfied", card_id="card-1"),
    ]

    summary = post_experience_review_summary_from_events(events)

    assert summary["post_review_count"] == 1
    assert summary["outcome_counts"]["unknown"] == 0
    assert summary["outcome_counts"]["went_satisfied"] == 1
    assert summary["regret_rate"] == 0.0
    assert summary["satisfaction_rate"] == 1.0


def test_post_experience_summary_accepts_payload_outcome_fallback() -> None:
    events = [
        _event("recommendation_card_accepted", card_id="card-1"),
        _event("custom_post_review_event", card_id="card-1", outcome="went_regretted"),
    ]

    summary = post_experience_review_summary_from_events(events)

    assert summary["post_review_count"] == 1
    assert summary["outcome_counts"]["went_regretted"] == 1
    assert summary["reviewed_after_acceptance_rate"] == 1.0
