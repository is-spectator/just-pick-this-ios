from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_test_scripts_are_executable() -> None:
    for script in (
        "scripts/test.sh",
        "scripts/test_unit.sh",
        "scripts/test_security_gate.sh",
        "scripts/test_quality_gate.sh",
        "scripts/migrate.sh",
        "scripts/seed.sh",
        "scripts/quality_gate.py",
        "scripts/validate_benchmark_results.py",
        "scripts/run_product_benchmark.py",
    ):
        path = ROOT / script
        assert path.exists()
        assert os.access(path, os.X_OK)


def test_backend_ci_workflow_exists() -> None:
    workflow = ROOT / ".github/workflows/backend-ci.yml"
    assert workflow.exists()
    text = workflow.read_text()
    assert "postgres:" in text
    assert "alembic upgrade head" in text
    assert "pytest" in text
    assert "ruff check app tests" in text
    assert "benchmark_quality_report.py" in text
    assert "quality_gate.py" in text
    assert "validate_benchmark_results.py" in text
    assert "run_product_benchmark.py" in text
    assert "--require-latency-ms" in text
    assert "benchmarks/reports/latest/results.jsonl" in text
    assert "actions/upload-artifact@v4" in text
    assert "quality_gate_report.md" in text
    assert "results_guard_report.md" in text
    assert "quality-gate-smoke-report" in text
    assert "quality-gate-strict-report" in text
    assert "backend/.ci-artifacts/quality-gate-smoke" in text
    assert "--max-p50-latency-ms 3500" in text
    assert "--max-p95-latency-ms 6000" in text


def test_test_script_has_clear_docker_error() -> None:
    text = (ROOT / "scripts/test.sh").read_text()
    assert "Docker is required for integration tests" in text
    assert "Docker daemon is not running" in text


def test_prod_start_script_does_not_use_dev_extra() -> None:
    text = (ROOT / "scripts/start_prod.sh").read_text()
    assert "uv run --extra dev" not in text
    assert "uv run uvicorn" in text
