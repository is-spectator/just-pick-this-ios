from __future__ import annotations

import json

import pytest

from app.eval.reporting import generate_quality_reports_from_files, main, write_quality_reports


def _valid_recommendation_response() -> dict[str, object]:
    return {
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
                    "displayable": True,
                    "is_ai_generated": False,
                    "source_url": "https://example.com/sanlitun-sichuan",
                    "source_domain": "example.com",
                },
                "evidence_ids": ["hit-1"],
                "provenance": {"retrieval_run_id": "retrieval-1"},
            }
        },
        "tool_calls": [{"name": "create_recommendation_card", "status": "succeeded"}],
        "metadata": {"agent_run_id": "agent-1", "retrieval_run_id": "retrieval-1"},
    }


def _valid_help_card_response() -> dict[str, object]:
    return {
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
        "metadata": {"agent_run_id": "agent-2", "retrieval_run_id": "retrieval-2"},
    }


def test_quality_report_generates_all_files_and_classifies_seed_gap(tmp_path) -> None:
    cases = [
        {
            "id": "recommendation-pass",
            "category": "area_food",
            "message": "三里屯川菜帮我选一个",
            "expected": {
                "response_kind": "recommendation_card",
                "location_state": "in_area",
                "target_type": "restaurant",
            },
        },
        {
            "id": "seed-gap-help-card",
            "category": "area_food",
            "message": "陌生商圈想吃清淡点",
            "expected": {
                "response_kind": "recommendation_card",
                "location_state": "in_area",
                "target_type": "restaurant",
                "allow_help_card_fallback": True,
            },
        },
        {
            "id": "wrong-recommendation",
            "category": "venue_ordering",
            "message": "我在三里屯海底捞，两个人不太能吃辣，帮我点",
            "expected": {
                "response_kind": "recommendation_card",
                "location_state": "in_venue",
                "target_type": "ordering_bundle",
            },
        },
    ]
    wrong_recommendation = _valid_recommendation_response()
    wrong_recommendation["location_state"] = "in_area"

    rows = [
        {"case": cases[0], "response": _valid_recommendation_response()},
        {"case": cases[1], "response": _valid_help_card_response()},
        {"case": cases[2], "response": wrong_recommendation},
    ]

    paths = write_quality_reports(rows, tmp_path, benchmark_cases=cases)

    assert {path.name for path in paths.values()} == {
        "summary.md",
        "quality_report.json",
        "quality_attribution.json",
        "quality_attribution.jsonl",
        "quality_report.md",
        "case_quality_scores.jsonl",
        "low_quality_cases.md",
        "seed_gap_report.md",
        "seed_gap_report.json",
        "seed_candidates.jsonl",
        "seed_candidates.json",
        "seed_candidates.md",
        "agent_fix_issues.json",
        "agent_fix_issues.jsonl",
        "agent_fix_issues.md",
        "pipi_agent_improvement_report.md",
        "benchmark_coverage_report.md",
        "shadow_comparison_report.md",
        "shadow_comparison_report.json",
        "shadow_decisions.jsonl",
        "experiment_lift_report.md",
        "experiment_lift_report.json",
        "shadow_promotion_candidates.jsonl",
        "shadow_promotion_candidates.json",
        "shadow_promotion_candidates.md",
        "index.md",
        "p2_aggregate.md",
    }
    report = json.loads((tmp_path / "quality_report.json").read_text(encoding="utf-8"))
    assert report["summary"]["score_formula"] == (
        "quality_score = max(0.0, 1.0 - sum(dimension_penalties.values()))"
    )
    for case_score in report["cases"]:
        expected_score = round(
            max(0.0, 1.0 - sum(case_score["dimension_penalties"].values())),
            4,
        )
        assert case_score["quality_score"] == expected_score
        assert set(case_score["dimensions"])
    buckets = {case_score["case_id"]: case_score["report_bucket"] for case_score in report["cases"]}
    assert buckets["seed-gap-help-card"] == "seed_gap"
    assert buckets["wrong-recommendation"] == "agent_improvement"

    seed_gap_text = (tmp_path / "seed_gap_report.md").read_text(encoding="utf-8")
    improvement_text = (tmp_path / "pipi_agent_improvement_report.md").read_text(
        encoding="utf-8"
    )
    assert "seed-gap-help-card" in seed_gap_text
    assert "wrong-recommendation" not in seed_gap_text
    assert "wrong-recommendation" in improvement_text
    assert "seed-gap-help-card" not in improvement_text

    generated_dir = tmp_path / "generated"
    generated_index = (generated_dir / "index.md").read_text(encoding="utf-8")
    generated_issues = sorted(generated_dir.glob("issuer_*.md"))
    assert generated_issues
    assert "wrong-recommendation" in generated_index
    assert "seed-gap-help-card" in generated_index

    generated_text = "\n".join(path.read_text(encoding="utf-8") for path in generated_issues)
    assert "`data_seed` / `seed_gap`" in generated_text
    assert "只补本地 seed" in generated_text
    assert "`router` / `agent_improvement`" in generated_text
    assert "顶层路由" in generated_text
    assert "agent-1" in generated_text

    seed_candidates = [
        json.loads(line)
        for line in (tmp_path / "seed_candidates.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert seed_candidates
    assert {
        "intent_key",
        "slots",
        "source_cases",
        "priority",
        "priority_score",
    } <= set(seed_candidates[0])
    assert seed_candidates[0]["source_cases"][0]["case_id"] == "seed-gap-help-card"


def test_quality_report_generates_shadow_comparison_files(tmp_path) -> None:
    cases = [
        {"id": "shadow-mismatch", "category": "area_food", "message": "三里屯川菜帮我选一个"},
        {"id": "shadow-schema-error", "category": "venue_order", "message": "店里帮我点菜"},
        {"id": "shadow-provider-error", "group": "smalltalk", "message": "你好"},
        {"id": "shadow-timeout", "category": "travel_shopping", "message": "首尔买礼物"},
        {"id": "no-shadow", "category": "area_food", "message": "没开 shadow"},
    ]
    rows = [
        {
            "case": cases[0],
            "response": {
                "response_kind": "recommendation_card",
                "tool_calls": [{"name": "create_recommendation_card"}],
                "metadata": {
                    "agent_run_id": "trace-1",
                    "shadow_summary": {
                        "enabled": True,
                        "schema_valid": True,
                        "deterministic_decision": {
                            "type": "tool",
                            "tool_name": "create_recommendation_card",
                        },
                    },
                    "shadow_reasoner_result": {
                        "type": "tool",
                        "tool_name": "draft_help_card",
                    },
                },
            },
        },
        {
            "case": cases[1],
            "output_json": {
                "agent_run_id": "trace-2",
                "shadow_summary": {
                    "enabled": True,
                    "schema_valid": False,
                    "error_type": "schema_error",
                },
            },
        },
        {
            "case": cases[2],
            "loop_trace": [
                {
                    "event": "shadow_llm_result",
                    "payload": {
                        "shadow_summary": {
                            "enabled": True,
                            "status": "provider_error",
                            "trace_id": "trace-3",
                        }
                    },
                }
            ],
        },
        {
            "case": cases[3],
            "loop_trace": [
                {
                    "event": "shadow_llm_result",
                    "data": {
                        "shadow_summary": {
                            "enabled": True,
                            "status": "timeout",
                            "trace_id": "trace-4",
                        }
                    },
                }
            ],
        },
        {"case": cases[4], "response": {"response_kind": "chitchat"}},
    ]

    paths = write_quality_reports(rows, tmp_path, benchmark_cases=cases)

    report = json.loads(paths["shadow_comparison_json"].read_text(encoding="utf-8"))
    assert report["summary"]["total_cases_with_shadow"] == 4
    assert report["summary"]["shadow_enabled_count"] == 4
    assert report["summary"]["schema_valid_count"] == 1
    assert report["summary"]["schema_error_count"] == 1
    assert report["summary"]["provider_error_count"] == 1
    assert report["summary"]["timeout_count"] == 1
    assert report["summary"]["deterministic_vs_shadow_mismatch_count"] == 1
    assert report["summary"]["deterministic_shadow_mismatch_count"] == 1
    assert report["summary"]["shadow_improvement_candidates"] == 0
    assert "unsafe_shadow_count" in report["summary"]
    assert report["mismatch_by_group"] == {"area_food": 1}
    assert report["top_20_mismatches"][0]["case_id"] == "shadow-mismatch"
    assert report["top_20_mismatches"][0]["deterministic"] == "tool:create_recommendation_card"
    assert report["top_20_mismatches"][0]["shadow"] == "tool:draft_help_card"

    decisions = [
        json.loads(line)
        for line in paths["shadow_decisions_jsonl"].read_text(encoding="utf-8").splitlines()
    ]
    assert decisions[0]["case_id"] == "shadow-mismatch"
    assert decisions[0]["deterministic"] == "tool:create_recommendation_card"
    assert decisions[0]["shadow"] == "tool:draft_help_card"
    assert decisions[0]["mismatch"] is True
    assert decisions[0]["trace_id"] == "trace-1"
    assert "quality_delta" in decisions[0]
    assert "unsafe_to_promote_reason" in decisions[0]
    assert len(decisions) == 4
    assert "shadow-mismatch" in paths["shadow_comparison_markdown"].read_text(
        encoding="utf-8"
    )
    promotion_candidates = [
        json.loads(line)
        for line in paths["shadow_promotion_candidates_jsonl"].read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    by_case = {str(row["case_id"]): row for row in promotion_candidates}
    assert {
        "shadow-mismatch",
        "shadow-schema-error",
        "shadow-provider-error",
        "shadow-timeout",
    } <= set(by_case)
    assert by_case["shadow-mismatch"]["autopromote"] is False
    assert by_case["shadow-mismatch"]["review_required"] is True
    assert by_case["shadow-mismatch"]["candidate_type"] == "decision_mismatch_review"
    assert by_case["shadow-schema-error"]["candidate_type"] == "shadow_runtime_reliability"
    assert "fix_shadow_schema_prompt" in by_case["shadow-schema-error"]["suggested_actions"]
    assert by_case["shadow-provider-error"]["priority"] == "P1"
    assert by_case["shadow-timeout"]["priority"] == "P1"
    promotion_json = json.loads(
        paths["shadow_promotion_candidates_json"].read_text(encoding="utf-8")
    )
    assert promotion_json["total"] == len(promotion_candidates)
    assert promotion_json["shadow_improvement_candidates"] == 0
    assert promotion_json["unsafe_shadow_count"] >= 0
    assert promotion_json["autopromote_count"] == 0
    assert promotion_json["review_required_count"] == len(promotion_candidates)
    assert "candidate_type_counts" in promotion_json
    promotion_markdown = paths["shadow_promotion_candidates_markdown"].read_text(
        encoding="utf-8"
    )
    assert "autopromote=false" in promotion_markdown
    assert "Shadow improvement candidates" in promotion_markdown
    assert "shadow-mismatch" in promotion_markdown


def test_generated_issues_aggregate_p2_degraded_cases(tmp_path) -> None:
    case = {
        "id": "missing-agent-run-warning",
        "category": "area_food",
        "message": "三里屯川菜帮我选一个",
        "expected": {
            "response_kind": "recommendation_card",
            "location_state": "in_area",
            "target_type": "restaurant",
        },
    }
    response = _valid_recommendation_response()
    response["metadata"] = {"retrieval_run_id": "retrieval-1"}
    response["data"]["recommendation_card"]["decision_factor"] = {
        "text": "三里屯附近想吃川菜，距离近且现场落座成本低。"
    }

    paths = write_quality_reports(
        [{"case": case, "response": response}],
        tmp_path,
        benchmark_cases=[case],
    )

    index_text = paths["generated_issues_index"].read_text(encoding="utf-8")
    p2_text = paths["generated_issues_p2_aggregate"].read_text(encoding="utf-8")
    assert "Individual P0/P1 issues | 0" in index_text
    assert "missing-agent-run-warning" in p2_text
    assert "agent_run_id_missing" in p2_text
    assert list((tmp_path / "generated").glob("issuer_*.md")) == []


def test_report_cli_generates_coverage_only_files_with_benchmark_only(tmp_path) -> None:
    benchmark = tmp_path / "benchmark.json"
    benchmark.write_text(
        json.dumps(
            {
                "suite_id": "unit",
                "version": 1,
                "cases": [
                    {
                        "id": "case-1",
                        "category": "area_food",
                        "message": "三里屯川菜帮我选一个",
                        "expected": {
                            "response_kind": "recommendation_card",
                            "location_state": "in_area",
                            "target_type": "restaurant",
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert main(["--benchmark", str(benchmark), "--out", str(tmp_path / "reports")]) == 0

    assert (tmp_path / "reports" / "quality_report.md").exists()
    assert "coverage-only" in (tmp_path / "reports" / "quality_report.md").read_text(
        encoding="utf-8"
    )
    assert "No shadow decisions evaluated" in (
        tmp_path / "reports" / "shadow_comparison_report.md"
    ).read_text(encoding="utf-8")
    summary_text = (tmp_path / "reports" / "summary.md").read_text(encoding="utf-8")
    assert "report_mode: `coverage_only`" in summary_text
    assert "evaluated_case_count: `0`" in summary_text
    assert (tmp_path / "reports" / "case_quality_scores.jsonl").exists()
    assert (tmp_path / "reports" / "seed_gap_report.md").exists()
    assert (tmp_path / "reports" / "pipi_agent_improvement_report.md").exists()
    shadow_report = json.loads(
        (tmp_path / "reports" / "shadow_comparison_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert shadow_report["summary"]["total_cases_with_shadow"] == 0
    assert (tmp_path / "reports" / "shadow_decisions.jsonl").read_text(
        encoding="utf-8"
    ) == ""


def test_generate_quality_reports_from_files_rejects_empty_results(tmp_path) -> None:
    results = tmp_path / "empty.jsonl"
    results.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="zero evaluated cases"):
        generate_quality_reports_from_files(results_path=results, output_dir=tmp_path / "reports")


def test_report_cli_rejects_all_invalid_result_rows(tmp_path) -> None:
    results = tmp_path / "invalid.json"
    results.write_text(json.dumps([None, "bad"]), encoding="utf-8")

    assert main(["--results", str(results), "--out", str(tmp_path / "reports")]) == 2
