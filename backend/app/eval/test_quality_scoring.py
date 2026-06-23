from __future__ import annotations

import json

from app.eval.quality_scoring import score_case_result
from app.eval.reporting import benchmark_coverage, write_quality_reports


def test_recommendation_card_quality_passes_with_tool_retrieval_and_trusted_image() -> None:
    case = {
        "id": "area_food_pass",
        "message": "我在三里屯想吃川菜，就选一个",
        "expected": {
            "response_kind": "recommendation_card",
            "location_state": "in_area",
            "target_type": "restaurant",
        },
    }
    response = {
        "response_kind": "recommendation_card",
        "location_state": "in_area",
        "data": {
            "recommendation_card": {
                "title": "三里屯川菜馆",
                "target_type": "restaurant",
                "item": {"title": "三里屯川菜馆", "category": "restaurant"},
                "decision_factor": {"text": "离你近，现场落座也比较稳。"},
                "image": {"id": "img-1", "verified": True, "is_ai_generated": False},
                "evidence_ids": ["hit-1"],
                "provenance": {"retrieval_run_id": "run-1"},
            }
        },
        "tool_calls": [{"name": "create_recommendation_card", "status": "succeeded"}],
        "metadata": {"agent_run_id": "agent-1", "retrieval_run_id": "run-1"},
    }

    score = score_case_result(case, response)

    assert score.status == "passed"
    assert score.quality_score == 1.0
    assert score.issues == []


def test_recommendation_to_specific_help_card_can_be_degraded() -> None:
    case = {
        "id": "area_food_degraded",
        "message": "我在陌生商圈想吃清淡点",
        "expected": {
            "response_kind": "recommendation_card",
            "location_state": "in_area",
            "target_type": "restaurant",
            "allow_help_card_fallback": True,
        },
    }
    response = {
        "response_kind": "help_card_draft",
        "location_state": "in_area",
        "data": {
            "help_card": {
                "title": "陌生商圈清淡餐厅，求一个",
                "context": {"area": "陌生商圈", "preference": "清淡"},
                "wants": ["清淡一点、适合现场去的餐厅"],
                "avoids": ["重辣和纯榜单推荐"],
                "location_state": "in_area",
            }
        },
        "tool_calls": [{"name": "draft_help_card", "status": "succeeded"}],
        "metadata": {"agent_run_id": "agent-1", "retrieval_run_id": "run-1"},
    }

    score = score_case_result(case, response)

    assert score.status == "degraded"
    assert score.quality_score == 0.75
    assert [issue.code for issue in score.issues] == ["recommendation_degraded_to_help_card"]


def test_generic_help_card_fails_quality() -> None:
    case = {
        "id": "help_card_generic",
        "message": "附近有啥",
        "expected": {"response_kind": "help_card_draft", "location_state": "in_area"},
    }
    response = {
        "response_kind": "help_card_draft",
        "location_state": "in_area",
        "data": {
            "help_card": {
                "title": "求一个",
                "context": {},
                "wants": ["好吃"],
                "avoids": ["踩雷"],
                "location_state": "in_area",
            }
        },
        "tool_calls": [{"name": "draft_help_card", "status": "succeeded"}],
        "metadata": {"agent_run_id": "agent-1", "retrieval_run_id": "run-1"},
    }

    score = score_case_result(case, response)
    issue_codes = {issue.code for issue in score.issues}

    assert score.status == "failed"
    assert "help_card_title_too_generic" in issue_codes
    assert "help_card_missing_context" in issue_codes


def test_reporting_writes_quality_and_coverage_files(tmp_path) -> None:
    benchmark_cases = [
        {
            "id": "case-pass",
            "category": "area_food",
            "message": "三里屯川菜帮我选一个",
            "expected": {
                "response_kind": "recommendation_card",
                "location_state": "in_area",
                "target_type": "restaurant",
            },
        },
        {
            "id": "case-help",
            "category": "insufficient_evidence",
            "message": "陌生地方附近吃什么",
            "expected": {"response_kind": "help_card_draft", "location_state": "in_area"},
        },
    ]
    rows = [
        {
            "case": benchmark_cases[0],
            "response": {
                "response_kind": "recommendation_card",
                "location_state": "in_area",
                "data": {
                    "recommendation_card": {
                        "title": "三里屯川菜馆",
                        "target_type": "restaurant",
                        "item": {"title": "三里屯川菜馆", "category": "restaurant"},
                        "decision_factor": {"text": "离你近，现场落座也比较稳。"},
                        "image": {
                            "id": "img-1",
                            "verified": True,
                            "is_ai_generated": False,
                        },
                        "evidence_ids": ["hit-1"],
                    }
                },
                "tool_calls": [{"name": "create_recommendation_card"}],
                "metadata": {"agent_run_id": "agent-1", "retrieval_run_id": "run-1"},
            },
        },
        {"case": benchmark_cases[1], "response": {"response_kind": "unknown"}},
    ]

    paths = write_quality_reports(rows, tmp_path, benchmark_cases=benchmark_cases)

    assert {path.name for path in paths.values()} == {
        "quality_report.json",
        "quality_report.md",
        "case_quality_scores.jsonl",
        "low_quality_cases.md",
        "seed_gap_report.md",
        "pipi_agent_improvement_report.md",
        "benchmark_coverage_report.md",
        "shadow_comparison_report.md",
        "shadow_comparison_report.json",
        "shadow_decisions.jsonl",
    }
    report = json.loads((tmp_path / "quality_report.json").read_text(encoding="utf-8"))
    assert report["summary"]["total"] == 2
    assert report["summary"]["failed"] == 1
    assert "response_kind_mismatch" in (tmp_path / "low_quality_cases.md").read_text(
        encoding="utf-8"
    )

    coverage = benchmark_coverage(benchmark_cases)
    assert coverage["schema_valid"] is True
    assert coverage["by_expected_kind"] == {
        "help_card_draft": 1,
        "recommendation_card": 1,
    }
