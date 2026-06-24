from __future__ import annotations

from app.services.answerer_quality import (
    answerer_quality_summary_from_counts,
    calculate_answerer_quality_rates,
    calculate_answerer_quality_score,
    reputation_tier,
)


def test_answerer_quality_score_rewards_useful_answerers() -> None:
    score = calculate_answerer_quality_score(
        submitted_count=5,
        reward_granted_count=4,
        reward_rejected_count=0,
        review_rejection_count=0,
    )

    assert score >= 0.85
    assert (
        reputation_tier(
            submitted_count=5,
            reward_granted_count=4,
            reward_rejected_count=0,
            review_rejection_count=0,
            quality_score=score,
        )
        == "reliable"
    )


def test_answerer_quality_score_penalizes_rejections_and_review_tasks() -> None:
    score = calculate_answerer_quality_score(
        submitted_count=4,
        reward_granted_count=0,
        reward_rejected_count=2,
        review_rejection_count=1,
    )

    assert score < 0.4
    assert (
        reputation_tier(
            submitted_count=4,
            reward_granted_count=0,
            reward_rejected_count=2,
            review_rejection_count=1,
            quality_score=score,
        )
        == "at_risk"
    )


def test_answerer_quality_rates_track_granted_and_spam_answers() -> None:
    rates = calculate_answerer_quality_rates(
        submitted_count=10,
        reward_granted_count=6,
        reward_rejected_count=1,
        review_rejection_count=2,
    )

    assert rates == {
        "granted_rate": 0.6,
        "spam_answer_rate": 0.3,
        "reward_rejected_rate": 0.1,
        "review_rejection_rate": 0.2,
    }


def test_answerer_quality_summary_handles_empty_denominators() -> None:
    summary = answerer_quality_summary_from_counts(
        submitted_count=0,
        reward_granted_count=0,
        reward_rejected_count=0,
        review_rejection_count=0,
    )

    assert summary["rates"]["granted_rate"] is None
    assert summary["rates"]["spam_answer_rate"] is None
    assert summary["negative_answer_count"] == 0
