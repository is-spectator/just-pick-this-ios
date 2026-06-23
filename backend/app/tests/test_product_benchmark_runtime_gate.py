from __future__ import annotations

import importlib.util
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


def test_product_benchmark_runtime_gate_counts_non_product_rows() -> None:
    runner = _load_runner()

    gate = runner._product_runtime_gate(
        [
            {
                "case_id": "ok-case",
                "status": "passed",
                "status_code": 200,
                "response": {"metadata": {"runtime_path": "product"}},
            },
            {
                "case_id": "bypass-case",
                "category": "area_food",
                "status": "failed",
                "status_code": 200,
                "issues": ["runtime_bypass"],
                "response": {"metadata": {"runtime_path": "eval_bypass"}},
            },
        ]
    )

    assert gate["ok"] is False
    assert gate["total_rows"] == 2
    assert gate["failed_rows"] == 1
    assert gate["failure_samples"][0]["case_id"] == "bypass-case"
    assert gate["failure_samples"][0]["runtime_path"] == "eval_bypass"


def test_product_benchmark_runtime_gate_passes_clean_product_rows() -> None:
    runner = _load_runner()

    gate = runner._product_runtime_gate(
        [
            {
                "case_id": "ok-case",
                "status": "passed",
                "status_code": 200,
                "response": {"metadata": {"runtime_path": "product"}},
            },
        ]
    )

    assert gate == {
        "ok": True,
        "total_rows": 1,
        "failed_rows": 0,
        "failure_samples": [],
    }
