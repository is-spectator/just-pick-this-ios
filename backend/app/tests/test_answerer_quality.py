from __future__ import annotations

from app.services.answerer_quality import calculate_answerer_quality_score, reputation_tier


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

