from __future__ import annotations

import json
from pathlib import Path

from app.services.eval_review_service import (
    append_case_review,
    card_contract_summary,
    low_quality_queue_summary,
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


def test_low_quality_queue_summary_tracks_cause_review_and_trace_coverage(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-3"
    run_dir.mkdir()
    _write_jsonl(
        run_dir / "quality_attribution.jsonl",
        [
            {
                "case_id": "seed-gap-case",
                "group": "area_food",
                "message": "朝阳区热干面",
                "primary_cause": "seed_gap",
                "quality": {"overall": 0.42},
                "trace": {"agent_run_id": "agent-1", "runtime_path": "product"},
            },
            {
                "case_id": "agent-bug-case",
                "group": "venue_order",
                "message": "三里屯海底捞帮我点",
                "primary_cause": "agent_bug",
                "quality": {"overall": 0.31},
                "trace": {"agent_run_id": "agent-2", "runtime_path": "product"},
            },
            {
                "case_id": "passed-case",
                "group": "smalltalk_app_help_unknown",
                "message": "你好",
                "primary_cause": "not_issue",
                "quality": {"overall": 0.96},
            },
        ],
    )
    _write_jsonl(
        run_dir / "case_quality_scores.jsonl",
        [
            {"case_id": "seed-gap-case", "quality_score": 0.42, "status": "failed"},
            {"case_id": "agent-bug-case", "quality_score": 0.31, "status": "failed"},
            {"case_id": "passed-case", "quality_score": 0.96, "status": "passed"},
        ],
    )
    append_case_review(
        tmp_path,
        "run-3",
        review_payload(
            run_id="run-3",
            case_id="seed-gap-case",
            action="accept_seed_gap",
            reviewer="human",
        ),
    )

    summary = low_quality_queue_summary(tmp_path, "run-3")

    assert summary["low_quality_count"] == 2
    assert summary["reviewed_count"] == 1
    assert summary["pending_review_count"] == 1
    assert summary["processing_rate"] == 0.5
    assert summary["trace_available_count"] == 2
    assert summary["trace_coverage_rate"] == 1.0
    assert summary["by_primary_cause"] == {"agent_bug": 1, "seed_gap": 1}
    assert summary["by_review_action"] == {"accept_seed_gap": 1}
    assert [item["case_id"] for item in summary["top_cases"]] == ["agent-bug-case", "seed-gap-case"]
    assert summary["top_cases"][1]["reviewed"] is True
    assert summary["top_cases"][1]["trace_replay"]["admin_trace_api_path"] == "/admin/api/traces/agent-1"


def test_card_contract_summary_tracks_single_decision_factor_and_legacy_field_violations(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run-4"
    run_dir.mkdir()
    _write_jsonl(
        run_dir / "case_quality_scores.jsonl",
        [
            {
                "case_id": "too-many-factors",
                "quality_score": 0.55,
                "status": "failed",
                "expected_kind": "recommendation_card",
                "actual_kind": "recommendation_card",
                "dimensions": {"card_contract": 0.4},
                "issues": [
                    {"code": "recommendation_card_decision_factor_must_be_single"},
                    {"code": "recommendation_card_must_use_singular_decision_factor"},
                ],
            },
            {
                "case_id": "legacy-fields",
                "quality_score": 0.7,
                "status": "degraded",
                "expected_kind": "recommendation_card",
                "actual_kind": "recommendation_card",
                "dimensions": {"card_contract": 0.65},
                "issues": [
                    {"code": "recommendation_card_forbidden_bullets"},
                    {"code": "recommendation_card_forbidden_followups"},
                ],
            },
            {
                "case_id": "clean-card",
                "quality_score": 1.0,
                "status": "passed",
                "expected_kind": "recommendation_card",
                "actual_kind": "recommendation_card",
                "dimensions": {"card_contract": 1.0},
                "issues": [],
            },
        ],
    )

    summary = card_contract_summary(tmp_path, "run-4")

    assert summary["scored_case_count"] == 3
    assert summary["average_card_contract_score"] == 0.6833
    assert summary["card_contract_issue_case_count"] == 2
    assert summary["too_many_decision_factor_count"] == 2
    assert summary["legacy_field_violation_count"] == 2
    assert summary["issue_counts"]["recommendation_card_forbidden_bullets"] == 1
    assert [item["case_id"] for item in summary["top_cases"]] == ["too-many-factors", "legacy-fields"]
    assert summary["metadata"]["contract"] == (
        "single item + single decision_factor + no reasons/bullets/followups/warning"
    )
