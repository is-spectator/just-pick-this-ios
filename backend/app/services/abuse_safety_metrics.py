from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ContentReviewTask, HelpCard

ABUSE_REVIEW_TASK_TYPES = {"help_card_rejected", "one_liner_rejected"}


def abuse_safety_summary(
    session: Session,
    *,
    since_hours: int = 24 * 30,
) -> dict[str, Any]:
    start = datetime.now(timezone.utc) - timedelta(hours=max(1, int(since_hours or 1)))
    help_cards = session.scalars(
        select(HelpCard).where(HelpCard.created_at >= start).order_by(HelpCard.created_at.asc())
    ).all()
    review_tasks = session.scalars(
        select(ContentReviewTask)
        .where(
            ContentReviewTask.created_at >= start,
            ContentReviewTask.task_type.in_(sorted(ABUSE_REVIEW_TASK_TYPES)),
        )
        .order_by(ContentReviewTask.created_at.asc())
    ).all()
    return abuse_safety_summary_from_records(
        help_cards=help_cards,
        review_tasks=review_tasks,
        window_start=start,
        window_hours=since_hours,
    )


def abuse_safety_summary_from_records(
    *,
    help_cards: list[Any],
    review_tasks: list[Any],
    window_start: datetime | None = None,
    window_hours: int | None = None,
) -> dict[str, Any]:
    help_card_count = len(help_cards)
    task_counts = {task_type: 0 for task_type in sorted(ABUSE_REVIEW_TASK_TYPES)}
    unsafe_help_card_ids: set[str] = set()
    unsafe_open_count = 0
    high_priority_count = 0
    for task in review_tasks:
        task_type = str(getattr(task, "task_type", "") or "")
        if task_type in task_counts:
            task_counts[task_type] += 1
        if str(getattr(task, "status", "") or "") == "open":
            unsafe_open_count += 1
        try:
            if int(getattr(task, "priority", 999) or 999) <= 20:
                high_priority_count += 1
        except (TypeError, ValueError):
            pass
        if task_type == "help_card_rejected":
            target_id = getattr(task, "target_record_id", None)
            if target_id:
                unsafe_help_card_ids.add(str(target_id))

    rejected_help_cards = task_counts["help_card_rejected"]
    rejected_one_liners = task_counts["one_liner_rejected"]
    total_review_tasks = rejected_help_cards + rejected_one_liners
    return {
        "window_start": window_start.isoformat() if window_start else None,
        "window_hours": window_hours,
        "help_card_count": help_card_count,
        "unsafe_help_card_count": len(unsafe_help_card_ids),
        "one_liner_rejected_count": rejected_one_liners,
        "abuse_review_task_count": total_review_tasks,
        "open_abuse_review_task_count": unsafe_open_count,
        "high_priority_abuse_task_count": high_priority_count,
        "task_counts": task_counts,
        "rates": {
            "unsafe_publish_rate": _rate(len(unsafe_help_card_ids), help_card_count),
            "flag_rate": _rate(total_review_tasks, help_card_count + rejected_one_liners),
            "one_liner_rejection_share": _rate(rejected_one_liners, total_review_tasks),
        },
        "metadata": {
            "version": "abuse_safety_summary_v1",
            "unsafe_publish_rate": "help_card_rejected / created_help_cards",
            "flag_rate": "(help_card_rejected + one_liner_rejected) / (created_help_cards + one_liner_rejected)",
            "tracked_task_types": sorted(ABUSE_REVIEW_TASK_TYPES),
        },
    }


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)
