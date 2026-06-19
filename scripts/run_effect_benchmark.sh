#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCHMARK="${BENCHMARK:-$ROOT/benchmarks/pipi_onsite_500_v1.json}"
OUT="${OUT:-$ROOT/reports/$(date -u +%Y%m%dT%H%M%SZ)}"
LIMIT_ARGS=()

if [[ "${LIMIT:-}" != "" ]]; then
  LIMIT_ARGS=(--limit "$LIMIT")
fi

cd "$ROOT/backend"
uv run python -m app.eval.product_benchmark_runner \
  --benchmark "$BENCHMARK" \
  --out "$OUT" \
  "${LIMIT_ARGS[@]}"
