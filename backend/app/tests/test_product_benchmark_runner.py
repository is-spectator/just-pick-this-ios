from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
RUNNER_PATH = ROOT / "scripts" / "run_product_benchmark.py"


def _load_runner() -> Any:
    spec = importlib.util.spec_from_file_location("run_product_benchmark", RUNNER_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_product_benchmark(path: Path) -> None:
    cases = [
        {
            "id": "product-datong-rec",
            "category": "area_food",
            "message": "我现在在大同喜晋道，不知道吃什么，给我推荐一个。",
            "expected": {
                "response_kind": "recommendation_card",
                "location_state": "in_venue",
                "target_type": "ordering_bundle",
            },
        },
        {
            "id": "product-korea-help",
            "category": "travel_shopping",
            "message": "韩国逛街，不去明洞，想小众",
            "expected": {
                "response_kind": "help_card_draft",
                "location_state": "unknown",
            },
        },
    ]
    path.write_text(
        json.dumps({"suite_id": "product_unit", "version": 1, "cases": cases}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_product_benchmark_runner_writes_latency_results_and_reports(
    tmp_path: Path,
    run_async: Any,
) -> None:
    runner = _load_runner()
    benchmark = tmp_path / "benchmark.json"
    output = tmp_path / "reports"
    _write_product_benchmark(benchmark)

    async def scenario() -> dict[str, Any]:
        return await runner.run_product_benchmark(
            runner.ProductBenchmarkConfig(
                benchmark_path=benchmark,
                output_dir=output,
                limit=2,
            )
        )

    summary = run_async(scenario)

    assert summary["ok"] is True
    assert summary["run_id"]
    assert summary["evaluated_cases"] == 2
    assert summary["guard"]["latency_rows"] == 2
    assert summary["stats"]["latency"]["count"] == 2
    assert summary["stats"]["latency"]["p50_ms"] is not None
    assert summary["stats"]["latency"]["p95_ms"] is not None
    assert summary["stats"]["status_code_counts"]["200"] == 2
    assert summary["stats"]["runtime_path_counts"]["product"] == 2
    assert summary["stats"]["response_kind_counts"]["recommendation_card"] == 1
    assert summary["stats"]["response_kind_counts"]["help_card_draft"] == 1
    assert len(summary["stats"]["slowest_cases"]) == 2
    results_path = output / "results.jsonl"
    assert results_path.exists()
    rows = [json.loads(line) for line in results_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert all(row["run_id"] == summary["run_id"] for row in rows)
    assert all(row["status"] == "passed" for row in rows)
    assert all(row["actual"]["response_kind"] in {"recommendation_card", "help_card_draft"} for row in rows)
    assert all(row["trace"]["runtime_path"] == "product" for row in rows)
    assert all(row["latency_ms"] >= 0 for row in rows)
    assert all(row["response"]["metadata"]["runtime_path"] == "product" for row in rows)
    assert all(not row.get("shadow_summary") for row in rows)

    by_id = {row["case_id"]: row for row in rows}
    assert by_id["product-datong-rec"]["metadata_loop_tool_calls"] == [
        "search_knowledge",
        "create_recommendation_card",
    ]
    assert by_id["product-korea-help"]["metadata_loop_tool_calls"] == [
        "search_knowledge",
        "draft_help_card",
    ]
    assert (output / "results_guard_report.json").exists()
    assert (output / "quality_report.json").exists()
    assert (output / "quality_attribution.jsonl").exists()
    assert (output / "product_benchmark_summary.json").exists()
    assert (output.parent / "latest.json").exists()
    summary_md = (output / "product_benchmark_summary.md").read_text(encoding="utf-8")
    assert "P50 latency" in summary_md
    assert "Slowest Cases" in summary_md


def test_product_benchmark_runner_cli_writes_results(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    benchmark = tmp_path / "benchmark.json"
    output = tmp_path / "reports"
    _write_product_benchmark(benchmark)

    assert (
        runner.main(
            [
                "--benchmark",
                str(benchmark),
                "--out",
                str(output),
                "--limit",
                "1",
                "--no-reports",
            ]
        )
        == 0
    )
    assert (output / "results.jsonl").exists()
    assert (output / "results_guard_report.md").exists()
