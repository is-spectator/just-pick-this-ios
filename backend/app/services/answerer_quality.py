from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import func, select

from app.models import ContentReviewTask, HelpAnswer, RewardEvent, User, UserBehaviorEvent
from app.services.runtime import ensure_user, session_scope


def calculate_answerer_quality_score(
    *,
    submitted_count: int,
    reward_granted_count: int,
    reward_rejected_count: int,
    review_rejection_count: int = 0,
) -> float:
    """Small, deterministic score for ranking answerers before a fuller reputation model."""

    submitted_count = max(0, int(submitted_count or 0))
    reward_granted_count = max(0, int(reward_granted_count or 0))
    reward_rejected_count = max(0, int(reward_rejected_count or 0))
    review_rejection_count = max(0, int(review_rejection_count or 0))
    if submitted_count == 0 and reward_granted_count == 0 and reward_rejected_count == 0 and review_rejection_count == 0:
        return 0.5

    total_outcomes = max(1, reward_granted_count + reward_rejected_count + review_rejection_count)
    granted_rate = reward_granted_count / total_outcomes
    negative_rate = (reward_rejected_count + review_rejection_count) / total_outcomes
    participation_bonus = min(submitted_count, 10) * 0.01
    score = 0.55 + granted_rate * 0.35 - negative_rate * 0.35 + participation_bonus
    return round(max(0.05, min(0.95, score)), 3)


def reputation_tier(
    *,
    submitted_count: int,
    reward_granted_count: int,
    reward_rejected_count: int,
    review_rejection_count: int,
    quality_score: float,
) -> str:
    if submitted_count <= 0:
        return "new"
    if review_rejection_count > 0 or reward_rejected_count > reward_granted_count:
        return "at_risk"
    if reward_granted_count >= 3 and quality_score >= 0.75:
        return "reliable"
    if quality_score >= 0.6:
        return "promising"
    return "new"


def get_answerer_quality(*, user_id: str | None = None, device_uid: str | None = None) -> dict[str, Any]:
    with session_scope() as session:
        user = ensure_user(session, device_uid=device_uid or user_id, user_id=user_id)
        answer_status_counts = _count_help_answers_by_status(session, user)
        reward_status_counts, reward_value_by_status = _count_rewards(session, user)
        review_rejections = _matching_one_liner_review_tasks(session, user)
        behavior_counts = _count_behavior_events(session, user)

        submitted_count = sum(answer_status_counts.values())
        reward_granted_count = reward_status_counts.get("granted", 0)
        reward_rejected_count = reward_status_counts.get("rejected", 0)
        review_rejection_count = len(review_rejections)
        quality_score = calculate_answerer_quality_score(
            submitted_count=submitted_count,
            reward_granted_count=reward_granted_count,
            reward_rejected_count=reward_rejected_count,
            review_rejection_count=review_rejection_count,
        )
        tier = reputation_tier(
            submitted_count=submitted_count,
            reward_granted_count=reward_granted_count,
            reward_rejected_count=reward_rejected_count,
            review_rejection_count=review_rejection_count,
            quality_score=quality_score,
        )
        return {
            "user": {
                "id": str(user.id),
                "device_uid": user.device_uid,
                "display_name": user.display_name,
            },
            "quality": {
                "score": quality_score,
                "tier": tier,
                "signals": _quality_signals(
                    submitted_count=submitted_count,
                    reward_granted_count=reward_granted_count,
                    reward_rejected_count=reward_rejected_count,
                    review_rejection_count=review_rejection_count,
                    behavior_counts=behavior_counts,
                ),
            },
            "answers": {
                "submitted_count": submitted_count,
                "status_counts": dict(answer_status_counts),
            },
            "rewards": {
                "pending_count": reward_status_counts.get("pending", 0),
                "granted_count": reward_granted_count,
                "rejected_count": reward_rejected_count,
                "pending_value": reward_value_by_status.get("pending", 0),
                "granted_value": reward_value_by_status.get("granted", 0),
                "rejected_value": reward_value_by_status.get("rejected", 0),
                "status_counts": dict(reward_status_counts),
            },
            "moderation": {
                "one_liner_rejected_count": review_rejection_count,
                "open_review_count": sum(1 for task in review_rejections if task.status == "open"),
                "recent_rejections": [
                    {
                        "id": str(task.id),
                        "reason": task.reason,
                        "issues": list((task.payload_json or {}).get("issues") or []),
                        "status": task.status,
                        "created_at": task.created_at,
                    }
                    for task in review_rejections[:10]
                ],
            },
            "behavior": {"event_counts": dict(behavior_counts)},
            "metadata": {
                "version": "answerer_quality_v1",
                "source_tables": [
                    "help_answers",
                    "reward_events",
                    "content_review_tasks",
                    "user_behavior_events",
                ],
            },
        }


def _count_help_answers_by_status(session: Any, user: User) -> Counter[str]:
    rows = session.execute(
        select(HelpAnswer.status, func.count())
        .where(HelpAnswer.answer_user_id == user.id)
        .group_by(HelpAnswer.status)
    )
    return Counter({str(status): int(count or 0) for status, count in rows})


def _count_rewards(session: Any, user: User) -> tuple[Counter[str], Counter[str]]:
    rows = session.execute(
        select(RewardEvent.status, func.count(), func.coalesce(func.sum(RewardEvent.value), 0))
        .where(RewardEvent.user_id == user.id)
        .group_by(RewardEvent.status)
    )
    counts: Counter[str] = Counter()
    values: Counter[str] = Counter()
    for status, count, value in rows:
        counts[str(status)] = int(count or 0)
        values[str(status)] = int(value or 0)
    return counts, values


def _count_behavior_events(session: Any, user: User) -> Counter[str]:
    rows = session.execute(
        select(UserBehaviorEvent.event_type, func.count())
        .where(UserBehaviorEvent.user_id == user.id)
        .group_by(UserBehaviorEvent.event_type)
    )
    return Counter({str(event_type): int(count or 0) for event_type, count in rows})


def _matching_one_liner_review_tasks(session: Any, user: User) -> list[ContentReviewTask]:
    user_tokens = {str(user.id)}
    if user.device_uid:
        user_tokens.add(user.device_uid)
    tasks = list(
        session.scalars(
            select(ContentReviewTask)
            .where(ContentReviewTask.task_type == "one_liner_rejected")
            .order_by(ContentReviewTask.created_at.desc())
        )
    )
    matched: list[ContentReviewTask] = []
    for task in tasks:
        payload = dict(task.payload_json or {})
        payload_tokens = {
            str(payload.get("user_id") or ""),
            str(payload.get("device_uid") or ""),
        }
        if payload_tokens & user_tokens:
            matched.append(task)
    return matched


def _quality_signals(
    *,
    submitted_count: int,
    reward_granted_count: int,
    reward_rejected_count: int,
    review_rejection_count: int,
    behavior_counts: Counter[str],
) -> list[str]:
    signals: list[str] = []
    if submitted_count:
        signals.append("submitted_answers")
    if reward_granted_count:
        signals.append("reward_granted")
    if reward_rejected_count:
        signals.append("reward_rejected")
    if review_rejection_count:
        signals.append("one_liner_rejected")
    for event_type in ("one_liner_reward_granted", "one_liner_reward_rejected"):
        if behavior_counts.get(event_type, 0):
            signals.append(event_type)
    return signals
