from __future__ import annotations

import json
from pathlib import Path

from app.services.eval_review_service import (
    append_case_review,
    review_alignment_summary,
    review_payload,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_review_alignment_tracks_human_agreement_without_database(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    _write_jsonl(
        run_dir / "quality_attribution.jsonl",
        [
            {
                "case_id": "seed-gap-case",
                "primary_cause": "seed_gap",
                "quality": {"overall": 0.42},
            },
            {
                "case_id": "agent-bug-case",
                "primary_cause": "agent_bug",
                "quality": {"overall": 0.31},
            },
        ],
    )
    _write_jsonl(
        run_dir / "case_quality_scores.jsonl",
        [
            {"case_id": "seed-gap-case", "quality_score": 0.42, "status": "failed"},
            {"case_id": "agent-bug-case", "quality_score": 0.31, "status": "failed"},
        ],
    )

    append_case_review(
        tmp_path,
        "run-1",
        review_payload(
            run_id="run-1",
            case_id="seed-gap-case",
            action="accept_seed_gap",
            reviewer="human",
        ),
    )
    append_case_review(
        tmp_path,
        "run-1",
        review_payload(
            run_id="run-1",
            case_id="agent-bug-case",
            action="accept_seed_gap",
            reviewer="human",
        ),
    )

    summary = review_alignment_summary(tmp_path, "run-1")

    assert summary["total_reviews"] == 2
    assert summary["comparable_reviews"] == 2
    assert summary["agreements"] == 1
    assert summary["disagreements"] == 1
    assert summary["agreement_rate"] == 0.5
    assert summary["target_agreement_rate"] == 0.75
    assert summary["target_met"] is False
    assert summary["by_review_action"] == {"accept_seed_gap": 2}
    assert summary["by_predicted_cause"] == {"agent_bug": 1, "seed_gap": 1}
    assert summary["disagreement_items"][0]["case_id"] == "agent-bug-case"


def test_review_alignment_marks_passed_case_as_not_issue(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-2"
    run_dir.mkdir()
    _write_jsonl(
        run_dir / "case_quality_scores.jsonl",
        [{"case_id": "pass-case", "quality_score": 0.95, "status": "passed"}],
    )
    append_case_review(
        tmp_path,
        "run-2",
        review_payload(
            run_id="run-2",
            case_id="pass-case",
            action="mark_not_issue",
            reviewer="human",
        ),
    )

    summary = review_alignment_summary(tmp_path, "run-2")

    assert summary["agreement_rate"] == 1.0
    assert summary["target_met"] is True
    assert summary["items"][0]["predicted_cause"] == "not_issue"
