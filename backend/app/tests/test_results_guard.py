from __future__ import annotations

import json

import pytest

from app.eval.results_guard import main, validate_benchmark_results


def _write_jsonl(path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_results_guard_accepts_valid_rows_with_latency(tmp_path) -> None:
    results = tmp_path / "results.jsonl"
    _write_jsonl(
        results,
        [
            {
                "case": {"id": "case-1", "message": "你好"},
                "response": {"response_kind": "chitchat", "ui_events": [], "data": {}},
                "latency_ms": 120,
            },
            {
                "case_id": "case-2",
                "message": "三里屯川菜",
                "status_code": 200,
                "latency_ms": "530.5",
            },
        ],
    )

    result = validate_benchmark_results(results, require_latency_ms=True)

    assert result["ok"] is True
    assert result["total_rows"] == 2
    assert result["latency_rows"] == 2


def test_results_guard_fails_empty_rows(tmp_path) -> None:
    results = tmp_path / "results.jsonl"
    results.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="zero evaluated cases"):
        validate_benchmark_results(results)


def test_results_guard_fails_missing_response_and_message(tmp_path) -> None:
    results = tmp_path / "results.jsonl"
    _write_jsonl(results, [{"case": {"id": "case-1"}}])

    with pytest.raises(ValueError) as exc_info:
        validate_benchmark_results(results)

    message = str(exc_info.value)
    assert "message_missing" in message
    assert "response_missing" in message


def test_results_guard_fails_missing_latency_when_required(tmp_path) -> None:
    results = tmp_path / "results.jsonl"
    _write_jsonl(
        results,
        [
            {
                "case": {"id": "case-1", "message": "你好"},
                "response": {"response_kind": "chitchat", "ui_events": [], "data": {}},
            }
        ],
    )

    with pytest.raises(ValueError, match="latency_ms_missing"):
        validate_benchmark_results(results, require_latency_ms=True)


def test_results_guard_cli_writes_report_and_exit_codes(tmp_path) -> None:
    results = tmp_path / "results.jsonl"
    _write_jsonl(
        results,
        [
            {
                "case": {"id": "case-1", "message": "你好"},
                "response": {"response_kind": "chitchat", "ui_events": [], "data": {}},
                "latency_ms": 120,
            }
        ],
    )

    assert (
        main(
            [
                "--results",
                str(results),
                "--require-latency-ms",
                "--out",
                str(tmp_path / "out"),
            ]
        )
        == 0
    )
    assert (tmp_path / "out" / "results_guard_report.json").exists()
    assert "Result: `passed`" in (tmp_path / "out" / "results_guard_report.md").read_text(
        encoding="utf-8"
    )

    bad_results = tmp_path / "bad-results.jsonl"
    _write_jsonl(bad_results, [{"case": {"id": "bad-1", "message": "你好"}}])
    assert (
        main(
            [
                "--results",
                str(bad_results),
                "--require-latency-ms",
                "--out",
                str(tmp_path / "bad-out"),
            ]
        )
        == 2
    )
    assert "failed" in (tmp_path / "bad-out" / "results_guard_report.md").read_text(
        encoding="utf-8"
    )
