from __future__ import annotations

import json

from app.eval.quality_gate import evaluate_quality_gate, main
from app.eval.reporting import write_quality_reports


def _valid_recommendation_response() -> dict[str, object]:
    return {
        "response_kind": "recommendation_card",
        "location_state": "in_area",
        "data": {
            "recommendation_card": {
                "title": "三里屯川菜馆",
                "target_type": "restaurant",
                "item": {"title": "三里屯川菜馆", "category": "restaurant"},
                "decision_factor": {"text": "三里屯附近想吃川菜，距离近且现场落座成本低。"},
                "image": {"id": "img-1", "verified": True, "is_ai_generated": False},
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


def test_quality_gate_passes_clean_report(tmp_path) -> None:
    case = {
        "id": "clean-card",
        "category": "area_food",
        "message": "三里屯川菜帮我选一个",
        "expected": {
            "response_kind": "recommendation_card",
            "location_state": "in_area",
            "target_type": "restaurant",
        },
    }
    write_quality_reports(
        [{"case": case, "response": _valid_recommendation_response()}],
        tmp_path,
        benchmark_cases=[case],
    )

    result = evaluate_quality_gate(tmp_path, min_pass_rate=1.0, min_average_quality=1.0)

    assert result["passed"] is True
    assert result["summary"]["p0_count"] == 0
    assert result["summary"]["p1_count"] == 0
    assert (tmp_path / "quality_gate_report.json").exists()
    assert "Result: `passed`" in (tmp_path / "quality_gate_report.md").read_text(
        encoding="utf-8"
    )


def test_quality_gate_fails_p0_wrong_kind(tmp_path) -> None:
    case = {
        "id": "wrong-kind",
        "message": "三里屯川菜帮我选一个",
        "expected": {"response_kind": "recommendation_card"},
    }
    write_quality_reports(
        [{"case": case, "response": {"response_kind": "chitchat", "ui_events": [], "data": {}}}],
        tmp_path,
        benchmark_cases=[case],
    )

    result = evaluate_quality_gate(tmp_path, min_pass_rate=0.0, min_average_quality=0.0)

    assert result["passed"] is False
    assert result["summary"]["p0_count"] == 1
    assert result["p0_cases"][0]["case_id"] == "wrong-kind"


def test_quality_gate_fails_seed_gap_as_p1(tmp_path) -> None:
    case = {
        "id": "seed-gap",
        "message": "陌生商圈想吃清淡点",
        "expected": {
            "response_kind": "recommendation_card",
            "location_state": "in_area",
            "target_type": "restaurant",
            "allow_help_card_fallback": True,
        },
    }
    write_quality_reports(
        [{"case": case, "response": _valid_help_card_response()}],
        tmp_path,
        benchmark_cases=[case],
    )

    result = evaluate_quality_gate(
        tmp_path,
        min_pass_rate=0.0,
        min_average_quality=0.0,
        max_p0=0,
        max_p1=0,
    )

    assert result["passed"] is False
    assert result["summary"]["p0_count"] == 0
    assert result["summary"]["p1_count"] == 1
    assert result["seed_gap_cases"][0]["case_id"] == "seed-gap"


def test_quality_gate_fails_shadow_schema_rate(tmp_path) -> None:
    case = {
        "id": "clean-card",
        "message": "三里屯川菜帮我选一个",
        "expected": {"response_kind": "recommendation_card"},
    }
    write_quality_reports(
        [{"case": case, "response": _valid_recommendation_response()}],
        tmp_path,
        benchmark_cases=[case],
    )
    (tmp_path / "shadow_comparison_report.json").write_text(
        json.dumps(
            {
                "summary": {
                    "total_cases_with_shadow": 10,
                    "shadow_enabled_count": 10,
                    "schema_valid_count": 9,
                    "provider_error_count": 0,
                    "timeout_count": 0,
                }
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_quality_gate(
        tmp_path,
        min_pass_rate=1.0,
        min_average_quality=1.0,
        min_shadow_schema_valid_rate=0.98,
    )

    assert result["passed"] is False
    assert result["summary"]["shadow_schema_valid_rate"] == 0.9
    assert any(check["name"] == "shadow_schema_valid_rate" for check in result["checks"])


def test_quality_gate_passes_latency_thresholds(tmp_path) -> None:
    case = {
        "id": "fast-card",
        "message": "三里屯川菜帮我选一个",
        "expected": {"response_kind": "recommendation_card"},
    }
    rows = []
    for index, latency_ms in enumerate((1000, 2000, 3000, 4000), start=1):
        response = _valid_recommendation_response()
        response["latency_ms"] = latency_ms
        rows.append({"case": {**case, "id": f"fast-card-{index}"}, "response": response})
    write_quality_reports(rows, tmp_path, benchmark_cases=[case])

    result = evaluate_quality_gate(
        tmp_path,
        min_pass_rate=1.0,
        min_average_quality=1.0,
        max_p50_latency_ms=3000,
        max_p95_latency_ms=4000,
    )

    assert result["passed"] is True
    assert result["summary"]["latency_case_count"] == 4
    assert result["summary"]["p50_latency_ms"] == 2500
    assert result["summary"]["p95_latency_ms"] == 3850


def test_quality_gate_fails_latency_thresholds(tmp_path) -> None:
    case = {
        "id": "slow-card",
        "message": "三里屯川菜帮我选一个",
        "expected": {"response_kind": "recommendation_card"},
    }
    rows = []
    for index, latency_ms in enumerate((1000, 7000), start=1):
        response = _valid_recommendation_response()
        response["latency_ms"] = latency_ms
        rows.append({"case": {**case, "id": f"slow-card-{index}"}, "response": response})
    write_quality_reports(rows, tmp_path, benchmark_cases=[case])

    result = evaluate_quality_gate(
        tmp_path,
        min_pass_rate=1.0,
        min_average_quality=1.0,
        max_p50_latency_ms=3500,
        max_p95_latency_ms=6000,
    )

    assert result["passed"] is False
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["p50_latency_ms"]["passed"] is False
    assert checks["p95_latency_ms"]["passed"] is False
    assert result["summary"]["p50_latency_ms"] == 4000
    assert result["summary"]["p95_latency_ms"] == 6700


def test_quality_gate_fails_requested_latency_without_latency_data(tmp_path) -> None:
    case = {
        "id": "clean-card",
        "message": "三里屯川菜帮我选一个",
        "expected": {"response_kind": "recommendation_card"},
    }
    write_quality_reports(
        [{"case": case, "response": _valid_recommendation_response()}],
        tmp_path,
        benchmark_cases=[case],
    )

    result = evaluate_quality_gate(
        tmp_path,
        min_pass_rate=1.0,
        min_average_quality=1.0,
        max_p95_latency_ms=6000,
    )

    assert result["passed"] is False
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["p95_latency_ms"]["observed"] is None


def test_quality_gate_cli_exit_codes(tmp_path) -> None:
    case = {
        "id": "clean-card",
        "message": "三里屯川菜帮我选一个",
        "expected": {"response_kind": "recommendation_card"},
    }
    write_quality_reports(
        [{"case": case, "response": _valid_recommendation_response()}],
        tmp_path,
        benchmark_cases=[case],
    )

    assert main(["--report-dir", str(tmp_path), "--min-pass-rate", "1.0"]) == 0
    assert main(["--report-dir", str(tmp_path), "--min-pass-rate", "1.1"]) == 2
    assert (
        main(
            [
                "--report-dir",
                str(tmp_path),
                "--min-pass-rate",
                "1.0",
                "--max-p95-latency-ms",
                "6000",
            ]
        )
        == 2
    )
