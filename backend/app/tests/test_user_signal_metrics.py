from __future__ import annotations

from types import SimpleNamespace

from app.services.user_signal_metrics import user_signal_summary_from_records


def _record(id: str) -> SimpleNamespace:
    return SimpleNamespace(id=id)


def _event(
    event_type: str,
    *,
    user_id: str | None = None,
    card_id: str | None = None,
    help_card_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        event_type=event_type,
        user_id=user_id,
        recommendation_card_id=card_id,
        help_card_id=help_card_id,
    )


def test_user_signal_summary_tracks_north_star_rates() -> None:
    summary = user_signal_summary_from_records(
        recommendation_cards=[_record("card-1"), _record("card-2"), _record("card-3"), _record("card-4")],
        help_cards=[_record("help-1"), _record("help-2")],
        events=[
            _event("recommendation_card_accepted", card_id="card-1"),
            _event("recommendation_card_rejected", card_id="card-2"),
            _event("recommendation_card_changed", card_id="card-3"),
            _event("ask_human_requested", card_id="card-3"),
            _event("help_card_published", help_card_id="help-1"),
            _event("help_feed_impression", user_id="answerer-1", help_card_id="help-1"),
            _event("help_feed_impression", user_id="answerer-2", help_card_id="help-2"),
            _event("one_liner_submitted", user_id="answerer-1", help_card_id="help-1"),
            _event("one_liner_reward_granted", user_id="answerer-1", help_card_id="help-1"),
            _event("final_recommendation_accepted", help_card_id="help-1"),
        ],
        window_hours=24,
    )

    assert summary["counts"]["recommendation_card_shown"] == 4
    assert summary["counts"]["accepted_recommendation_cards"] == 1
    assert summary["counts"]["followup_recommendation_cards"] == 2
    assert summary["counts"]["help_card_draft_shown"] == 2
    assert summary["counts"]["help_card_published"] == 1
    assert summary["counts"]["help_feed_impression_pairs"] == 2
    assert summary["counts"]["one_liner_submitted_pairs"] == 1
    assert summary["rates"] == {
        "accepted_card_rate": 0.25,
        "followup_rate": 0.5,
        "help_publish_rate": 0.5,
        "one_liner_submit_rate": 0.5,
    }
    assert summary["core_event_coverage"]["recommendation_card_accepted"] is True
    assert summary["core_event_coverage"]["one_liner_reward_rejected"] is False


def test_user_signal_summary_handles_empty_denominators() -> None:
    summary = user_signal_summary_from_records(recommendation_cards=[], help_cards=[], events=[])

    assert summary["rates"]["accepted_card_rate"] is None
    assert summary["rates"]["followup_rate"] is None
    assert summary["rates"]["help_publish_rate"] is None
    assert summary["rates"]["one_liner_submit_rate"] is None
    assert all(value is False for value in summary["core_event_coverage"].values())
