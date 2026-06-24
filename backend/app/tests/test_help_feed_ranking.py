from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.help_feed import (
    help_feed_conversion_summary_from_events,
    help_feed_rank_payload,
    help_feed_sort_key,
)


def _card(
    *,
    title: str = "默认求一句",
    context_text: str = "想找一个稳妥选择。",
    payload_json: dict | None = None,
    reward_value: int = 10,
    answer_count: int = 0,
    min_answers_required: int = 3,
    published_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        title=title,
        prompt=title,
        context_text=context_text,
        payload_json=payload_json or {"reward": {"value": reward_value, "label": f"+{reward_value}"}},
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


def test_help_feed_rank_payload_exposes_answerer_preference_match() -> None:
    card = _card(title="五道口韩餐，求一句", context_text="想吃韩餐，不想排太久。")

    rank = help_feed_rank_payload(
        card,
        answerer_preferences={
            "top_cuisines": [{"value": "韩餐", "score": 3}],
            "areas": [{"value": "五道口", "score": 2}],
        },
    )

    assert rank["preference_match"]["score"] > 0
    assert rank["preference_match"]["matched"] == {
        "top_cuisines": ["韩餐"],
        "areas": ["五道口"],
    }
    assert rank["score"] > help_feed_rank_payload(card)["score"]


def test_help_feed_sort_uses_preferences_as_same_tier_tiebreaker() -> None:
    matching = _card(title="五道口韩餐，求一句", context_text="想吃韩餐，不想排太久。")
    generic = _card(title="国贸午饭，求一句", context_text="想找现在能直接去的一家。")

    ordered = sorted(
        [generic, matching],
        key=lambda card: help_feed_sort_key(
            card,
            answerer_preferences={"top_cuisines": [{"value": "韩餐", "score": 3}]},
        ),
    )

    assert ordered == [matching, generic]


def _event(
    event_type: str,
    *,
    user_id: str,
    help_card_id: str,
    preference_score: int | None = None,
) -> SimpleNamespace:
    payload_json = {}
    if preference_score is not None:
        payload_json = {"feed_ranking": {"preference_match": {"score": preference_score}}}
    return SimpleNamespace(
        event_type=event_type,
        user_id=user_id,
        help_card_id=help_card_id,
        payload_json=payload_json,
    )


def test_help_feed_conversion_summary_measures_preference_match_uplift() -> None:
    events = [
        *[
            _event("help_feed_impression", user_id=f"baseline-user-{index}", help_card_id=f"baseline-card-{index}")
            for index in range(5)
        ],
        _event("one_liner_submitted", user_id="baseline-user-0", help_card_id="baseline-card-0"),
        *[
            _event(
                "help_feed_impression",
                user_id=f"matched-user-{index}",
                help_card_id=f"matched-card-{index}",
                preference_score=3,
            )
            for index in range(5)
        ],
        _event("one_liner_submitted", user_id="matched-user-0", help_card_id="matched-card-0"),
        _event("one_liner_submitted", user_id="matched-user-1", help_card_id="matched-card-1"),
    ]

    summary = help_feed_conversion_summary_from_events(events, target_uplift=0.2)

    assert summary["segments"]["baseline"] == {
        "impression_pairs": 5,
        "submitted_pairs": 1,
        "submit_rate": 0.2,
    }
    assert summary["segments"]["matched"] == {
        "impression_pairs": 5,
        "submitted_pairs": 2,
        "submit_rate": 0.4,
    }
    assert summary["one_liner_submit_rate_uplift"] == 1.0
    assert summary["target_met"] is True


def test_help_feed_conversion_summary_handles_missing_baseline() -> None:
    events = [
        _event("help_feed_impression", user_id="matched-user", help_card_id="matched-card", preference_score=1),
        _event("one_liner_submitted", user_id="matched-user", help_card_id="matched-card"),
    ]

    summary = help_feed_conversion_summary_from_events(events, target_uplift=0.2)

    assert summary["segments"]["baseline"]["impression_pairs"] == 0
    assert summary["matched_submit_rate"] == 1.0
    assert summary["baseline_submit_rate"] == 0.0
    assert summary["one_liner_submit_rate_uplift"] is None
    assert summary["target_met"] is False
