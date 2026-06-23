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


def test_product_benchmark_blocks_cleanly_when_database_unreachable(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    runner = _load_runner()
    benchmark = tmp_path / "benchmark.json"
    output = tmp_path / "reports"
    benchmark.write_text(
        json.dumps(
            {
                "suite_id": "db_blocked",
                "version": 1,
                "cases": [
                    {
                        "id": "db-blocked-case",
                        "category": "smalltalk",
                        "message": "你好",
                        "expected": {"response_kind": "chitchat"},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@127.0.0.1:1/nope")
    runner.get_settings.cache_clear()

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
        == 1
    )

    summary = json.loads((output / "product_benchmark_summary.json").read_text(encoding="utf-8"))
    assert summary["ok"] is False
    assert summary["status"] == "blocked"
    assert summary["evaluated_cases"] == 0
    assert summary["blocker"]["code"] == "database_unreachable"
    assert (output / "results.jsonl").read_text(encoding="utf-8") == ""
    assert "blocked" in (output / "product_benchmark_summary.md").read_text(encoding="utf-8")
    assert (output.parent / "latest.json").exists()
