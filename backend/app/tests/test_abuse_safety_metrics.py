from __future__ import annotations

from types import SimpleNamespace

from app.services.abuse_safety_metrics import abuse_safety_summary_from_records


def _help_card(id: str) -> SimpleNamespace:
    return SimpleNamespace(id=id)


def _review_task(
    task_type: str,
    *,
    target_record_id: str,
    status: str = "open",
    priority: int = 20,
) -> SimpleNamespace:
    return SimpleNamespace(
        task_type=task_type,
        target_record_id=target_record_id,
        status=status,
        priority=priority,
    )


def test_abuse_safety_summary_tracks_flag_and_unsafe_publish_rates() -> None:
    summary = abuse_safety_summary_from_records(
        help_cards=[_help_card("help-1"), _help_card("help-2"), _help_card("help-3"), _help_card("help-4")],
        review_tasks=[
            _review_task("help_card_rejected", target_record_id="help-1", priority=10),
            _review_task("one_liner_rejected", target_record_id="help-2", priority=30),
            _review_task("one_liner_rejected", target_record_id="help-3", status="closed", priority=10),
        ],
        window_hours=24,
    )

    assert summary["help_card_count"] == 4
    assert summary["unsafe_help_card_count"] == 1
    assert summary["one_liner_rejected_count"] == 2
    assert summary["abuse_review_task_count"] == 3
    assert summary["open_abuse_review_task_count"] == 2
    assert summary["high_priority_abuse_task_count"] == 2
    assert summary["task_counts"] == {"help_card_rejected": 1, "one_liner_rejected": 2}
    assert summary["rates"] == {
        "unsafe_publish_rate": 0.25,
        "flag_rate": 0.5,
        "one_liner_rejection_share": 0.6667,
    }


def test_abuse_safety_summary_handles_empty_denominators() -> None:
    summary = abuse_safety_summary_from_records(help_cards=[], review_tasks=[])

    assert summary["rates"]["unsafe_publish_rate"] is None
    assert summary["rates"]["flag_rate"] is None
    assert summary["rates"]["one_liner_rejection_share"] is None
    assert summary["abuse_review_task_count"] == 0
