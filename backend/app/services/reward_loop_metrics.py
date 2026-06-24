from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HelpAnswer, RewardEvent

REWARD_STATUSES = ("pending", "granted", "rejected")


def reward_loop_summary(
    session: Session,
    *,
    since_hours: int = 24 * 30,
) -> dict[str, Any]:
    start = datetime.now(timezone.utc) - timedelta(hours=max(1, int(since_hours or 1)))
    reward_events = session.scalars(
        select(RewardEvent).where(RewardEvent.created_at >= start).order_by(RewardEvent.created_at.asc())
    ).all()
    help_answers = session.scalars(
        select(HelpAnswer).where(HelpAnswer.created_at >= start).order_by(HelpAnswer.created_at.asc())
    ).all()
    return reward_loop_summary_from_records(
        reward_events=reward_events,
        help_answers=help_answers,
        window_start=start,
        window_hours=since_hours,
    )


def reward_loop_summary_from_records(
    *,
    reward_events: list[Any],
    help_answers: list[Any],
    window_start: datetime | None = None,
    window_hours: int | None = None,
) -> dict[str, Any]:
    reward_status_counts: Counter[str] = Counter()
    reward_value_by_status: Counter[str] = Counter()
    answer_status_counts: Counter[str] = Counter()
    answer_reward_status_counts: Counter[str] = Counter()
    answer_bound_count = 0
    help_card_bound_count = 0

    for event in reward_events:
        status = _status(getattr(event, "status", None))
        reward_status_counts[status] += 1
        reward_value_by_status[status] += _int(getattr(event, "value", 0))
        if getattr(event, "help_answer_id", None):
            answer_bound_count += 1
        if getattr(event, "help_card_id", None):
            help_card_bound_count += 1

    for answer in help_answers:
        answer_status_counts[str(getattr(answer, "status", "") or "unknown")] += 1
        answer_reward_status_counts[_status(getattr(answer, "reward_status", None))] += 1

    reward_event_count = len(reward_events)
    pending_count = reward_status_counts["pending"]
    granted_count = reward_status_counts["granted"]
    rejected_count = reward_status_counts["rejected"]
    settled_count = granted_count + rejected_count
    answer_count = len(help_answers)

    return {
        "window_start": window_start.isoformat() if window_start else None,
        "window_hours": window_hours,
        "reward_event_count": reward_event_count,
        "help_answer_count": answer_count,
        "pending_count": pending_count,
        "granted_count": granted_count,
        "rejected_count": rejected_count,
        "settled_count": settled_count,
        "pending_value": reward_value_by_status["pending"],
        "granted_value": reward_value_by_status["granted"],
        "rejected_value": reward_value_by_status["rejected"],
        "reward_status_counts": _status_dict(reward_status_counts),
        "reward_value_by_status": _status_dict(reward_value_by_status),
        "answer_status_counts": dict(answer_status_counts),
        "answer_reward_status_counts": _status_dict(answer_reward_status_counts),
        "rates": {
            "settlement_rate": _rate(settled_count, reward_event_count),
            "grant_rate": _rate(granted_count, reward_event_count),
            "rejection_rate": _rate(rejected_count, reward_event_count),
            "answer_binding_rate": _rate(answer_bound_count, reward_event_count),
            "help_card_binding_rate": _rate(help_card_bound_count, reward_event_count),
            "answer_reward_pending_rate": _rate(answer_reward_status_counts["pending"], answer_count),
        },
        "metadata": {
            "version": "reward_loop_summary_v1",
            "settlement_rate": "(granted + rejected) / reward_events",
            "answer_binding_rate": "reward_events_with_help_answer_id / reward_events",
            "help_card_binding_rate": "reward_events_with_help_card_id / reward_events",
            "tracked_statuses": list(REWARD_STATUSES),
        },
    }


def _status(value: Any) -> str:
    status = str(value or "pending")
    if status not in REWARD_STATUSES:
        return "pending"
    return status


def _status_dict(counter: Counter[str]) -> dict[str, int]:
    return {status: int(counter.get(status, 0)) for status in REWARD_STATUSES}


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)
