from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.help_feed import help_feed_rank_payload, help_feed_sort_key


def _card(
    *,
    reward_value: int = 10,
    answer_count: int = 0,
    min_answers_required: int = 3,
    published_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        payload_json={"reward": {"value": reward_value, "label": f"+{reward_value}"}},
        answer_count=answer_count,
        min_answers_required=min_answers_required,
        published_at=published_at or datetime(2026, 6, 23, tzinfo=timezone.utc),
        created_at=published_at or datetime(2026, 6, 23, tzinfo=timezone.utc),
    )


def test_help_feed_rank_payload_exposes_reward_and_scarcity() -> None:
    rank = help_feed_rank_payload(_card(reward_value=20, answer_count=1, min_answers_required=3))

    assert rank["reward_value"] == 20
    assert rank["answer_count"] == 1
    assert rank["remaining_answers"] == 2
    assert rank["score"] > 0


def test_help_feed_sort_prioritizes_high_reward_then_fewer_answers() -> None:
    high_reward = _card(reward_value=30, answer_count=2)
    low_answer_count = _card(reward_value=10, answer_count=0)
    filled = _card(reward_value=10, answer_count=3)

    ordered = sorted([filled, low_answer_count, high_reward], key=help_feed_sort_key)

    assert ordered == [high_reward, low_answer_count, filled]
