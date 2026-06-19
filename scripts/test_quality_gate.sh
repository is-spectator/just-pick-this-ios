#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
REPORT_DIR="${REPORT_DIR:-/tmp/pipi-quality-gate-smoke}"

cd "$BACKEND_DIR"

uv sync --extra dev
uv run --extra dev pytest \
  app/tests/test_quality_gate.py \
  app/tests/test_quality_report_generation.py \
  app/tests/test_benchmark_non_empty_guard.py \
  -q -rx

rm -rf "$REPORT_DIR"
uv run --extra dev python ../scripts/benchmark_quality_report.py \
  --benchmark ../benchmarks/pipi_onsite_500_v1.json \
  --out "$REPORT_DIR"

uv run --extra dev python ../scripts/quality_gate.py \
  --report-dir "$REPORT_DIR" \
  --min-pass-rate 0 \
  --min-average-quality 0 \
  --max-p0 0 \
  --max-p1 0
