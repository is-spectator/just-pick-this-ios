"""Importable product benchmark runner.

The canonical CLI still lives in ``scripts/run_product_benchmark.py`` for
operator convenience. This module gives tests and internal eval jobs a stable
``app.eval`` import path without duplicating the ASGI product-runner logic.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


def _load_script_module() -> ModuleType:
    root = Path(__file__).resolve().parents[3]
    script = root / "scripts" / "run_product_benchmark.py"
    spec = importlib.util.spec_from_file_location("pipi_product_benchmark_script", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load product benchmark script: {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_runner = _load_script_module()

ProductBenchmarkConfig: Any = _runner.ProductBenchmarkConfig
run_product_benchmark: Any = _runner.run_product_benchmark
main: Any = _runner.main


if __name__ == "__main__":
    raise SystemExit(main())
