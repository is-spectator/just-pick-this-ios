from __future__ import annotations

import json

import pytest

from app.eval.reporting import generate_quality_reports_from_files, main


def test_benchmark_only_is_coverage_only(tmp_path) -> None:
    benchmark = tmp_path / "benchmark.json"
    benchmark.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "case-1",
                        "message": "三里屯川菜",
                        "expected": {"response_kind": "recommendation_card"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert main(["--benchmark", str(benchmark), "--out", str(tmp_path / "out")]) == 0
    assert "coverage-only" in (tmp_path / "out" / "quality_report.md").read_text(
        encoding="utf-8"
    )
    assert "No shadow decisions evaluated" in (
        tmp_path / "out" / "shadow_comparison_report.md"
    ).read_text(encoding="utf-8")


def test_empty_results_file_fails(tmp_path) -> None:
    results = tmp_path / "results.jsonl"
    results.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="zero evaluated cases"):
        generate_quality_reports_from_files(results_path=results, output_dir=tmp_path / "out")


def test_non_empty_results_file_is_evaluated(tmp_path) -> None:
    results = tmp_path / "results.jsonl"
    results.write_text(
        json.dumps(
            {
                "case": {"id": "case-1", "expected": {"response_kind": "chitchat"}},
                "response": {"response_kind": "chitchat", "ui_events": [], "data": {}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    paths = generate_quality_reports_from_files(results_path=results, output_dir=tmp_path / "out")
    assert "Report mode: `evaluated`" in paths["quality_markdown"].read_text(encoding="utf-8")
