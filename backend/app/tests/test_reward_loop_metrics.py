from __future__ import annotations

from types import SimpleNamespace

from app.services.reward_loop_metrics import reward_loop_summary_from_records


def _reward_event(
    status: str,
    *,
    value: int = 10,
    help_answer_id: str | None = "answer-1",
    help_card_id: str | None = "help-1",
) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        value=value,
        help_answer_id=help_answer_id,
        help_card_id=help_card_id,
    )


def _help_answer(status: str, *, reward_status: str) -> SimpleNamespace:
    return SimpleNamespace(status=status, reward_status=reward_status)


def test_reward_loop_summary_tracks_settlement_and_binding_rates() -> None:
    summary = reward_loop_summary_from_records(
        reward_events=[
            _reward_event("pending", value=10),
            _reward_event("granted", value=20),
            _reward_event("rejected", value=10, help_answer_id=None),
            _reward_event("granted", value=10, help_card_id=None),
        ],
        help_answers=[
            _help_answer("submitted", reward_status="pending"),
            _help_answer("used", reward_status="granted"),
            _help_answer("rejected", reward_status="rejected"),
        ],
        window_hours=24,
    )

    assert summary["reward_event_count"] == 4
    assert summary["help_answer_count"] == 3
    assert summary["pending_count"] == 1
    assert summary["granted_count"] == 2
    assert summary["rejected_count"] == 1
    assert summary["settled_count"] == 3
    assert summary["pending_value"] == 10
    assert summary["granted_value"] == 30
    assert summary["rejected_value"] == 10
    assert summary["reward_status_counts"] == {"pending": 1, "granted": 2, "rejected": 1}
    assert summary["answer_reward_status_counts"] == {"pending": 1, "granted": 1, "rejected": 1}
    assert summary["rates"] == {
        "settlement_rate": 0.75,
        "grant_rate": 0.5,
        "rejection_rate": 0.25,
        "answer_binding_rate": 0.75,
        "help_card_binding_rate": 0.75,
        "answer_reward_pending_rate": 0.3333,
    }


def test_reward_loop_summary_handles_empty_denominators() -> None:
    summary = reward_loop_summary_from_records(reward_events=[], help_answers=[])

    assert summary["reward_event_count"] == 0
    assert summary["help_answer_count"] == 0
    assert summary["rates"]["settlement_rate"] is None
    assert summary["rates"]["grant_rate"] is None
    assert summary["rates"]["rejection_rate"] is None
    assert summary["rates"]["answer_binding_rate"] is None
    assert summary["rates"]["help_card_binding_rate"] is None
    assert summary["rates"]["answer_reward_pending_rate"] is None
