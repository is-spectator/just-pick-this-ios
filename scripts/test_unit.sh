#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"

cd "$BACKEND_DIR"

uv sync --extra dev
uv run --extra dev pytest \
  app/tests/test_no_secrets_committed.py \
  app/tests/test_shadow_schema_contract.py \
  app/tests/test_benchmark_non_empty_guard.py \
  app/tests/test_shadow_quality_diff.py \
  app/tests/test_quality_report_generation.py \
  app/tests/test_quality_gate.py \
  app/tests/test_benchmark_500_distribution.py \
  -q -rx
