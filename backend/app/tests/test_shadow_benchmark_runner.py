from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
RUNNER_PATH = ROOT / "scripts" / "run_shadow_benchmark.py"


def _load_runner() -> Any:
    spec = importlib.util.spec_from_file_location("run_shadow_benchmark", RUNNER_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_shadow_benchmark(path: Path) -> None:
    cases = [
        {
            "id": "shadow-datong-rec",
            "category": "area_food",
            "message": "我现在在大同喜晋道，不知道吃什么，给我推荐一个。",
            "expected": {
                "response_kind": "recommendation_card",
                "location_state": "in_venue",
                "target_type": "ordering_bundle",
            },
        },
        {
            "id": "shadow-korea-help",
            "category": "travel_shopping",
            "message": "韩国逛街，不去明洞，想小众",
            "expected": {
                "response_kind": "help_card_draft",
                "location_state": "unknown",
            },
        },
        {
            "id": "shadow-sijiminfu-rec",
            "category": "venue_order",
            "message": "第一次来四季民福，帮我点",
            "expected": {
                "response_kind": "recommendation_card",
                "location_state": "in_venue",
                "target_type": "ordering_bundle",
            },
        },
    ]
    path.write_text(
        json.dumps({"suite_id": "shadow_unit", "version": 1, "cases": cases}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_shadow_benchmark_runner_writes_non_empty_shadow_reports(
    tmp_path: Path,
    run_async: Any,
) -> None:
    runner = _load_runner()
    benchmark = tmp_path / "benchmark.json"
    output = tmp_path / "reports"
    _write_shadow_benchmark(benchmark)

    async def scenario() -> dict[str, Any]:
        return await runner.run_shadow_benchmark(
            runner.ShadowBenchmarkConfig(
                benchmark_path=benchmark,
                output_dir=output,
                limit=3,
                shadow_provider="mock_shadow",
            )
        )

    summary = run_async(scenario)

    assert summary["ok"] is True
    assert summary["evaluated_cases"] == 3
    assert summary["gate"]["shadow_schema_valid_rate"] == 1.0
    results_path = output / "shadow_results.jsonl"
    decisions_path = output / "shadow_decisions.jsonl"
    assert results_path.exists()
    assert decisions_path.exists()
    rows = [json.loads(line) for line in results_path.read_text(encoding="utf-8").splitlines()]
    decisions = [json.loads(line) for line in decisions_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 3
    assert len(decisions) == 3

    by_id = {row["case_id"]: row for row in rows}
    assert by_id["shadow-datong-rec"]["response"]["metadata"]["runtime_path"] == "product"
    assert by_id["shadow-korea-help"]["response"]["metadata"]["runtime_path"] == "product"
    assert by_id["shadow-datong-rec"]["metadata_loop_tool_calls"] == [
        "search_knowledge",
        "create_recommendation_card",
    ]
    assert by_id["shadow-korea-help"]["metadata_loop_tool_calls"] == [
        "search_knowledge",
        "draft_help_card",
    ]
    assert all(row["shadow_summary"]["enabled"] is True for row in rows)
    assert all(row["shadow_reasoner_results"] for row in rows)


def test_shadow_benchmark_gate_rejects_missing_shadow_events() -> None:
    runner = _load_runner()
    shadow_report = {
        "summary": {
            "total_cases_with_shadow": 0,
            "shadow_enabled_count": 0,
            "schema_valid_count": 0,
            "schema_error_count": 0,
            "provider_error_count": 0,
            "timeout_count": 0,
            "deterministic_vs_shadow_mismatch_count": 0,
        }
    }

    gate = runner.validate_shadow_gate(shadow_report, expected_case_count=2)

    assert gate["ok"] is False
    assert "shadow_case_count_mismatch expected=2 actual=0" in gate["failures"]
    assert "shadow_enabled_count_mismatch expected=2 actual=0" in gate["failures"]


def test_shadow_benchmark_gate_reports_provider_and_timeout_failures() -> None:
    runner = _load_runner()
    shadow_report = {
        "summary": {
            "total_cases_with_shadow": 3,
            "shadow_enabled_count": 3,
            "schema_valid_count": 3,
            "schema_error_count": 0,
            "provider_error_count": 1,
            "timeout_count": 1,
            "deterministic_vs_shadow_mismatch_count": 0,
        }
    }

    gate = runner.validate_shadow_gate(shadow_report, expected_case_count=3)

    assert gate["ok"] is False
    assert "shadow_provider_errors_present count=1" in gate["failures"]
    assert "shadow_timeouts_present count=1" in gate["failures"]
