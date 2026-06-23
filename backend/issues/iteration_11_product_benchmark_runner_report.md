# Iteration 11 Product Benchmark Runner Report

## Scope

This iteration adds a local product-path benchmark runner that writes evaluated
`results.jsonl` rows with `latency_ms`.

No iOS code, product routing, recommendation strategy, LLM behavior, or
AbilityCenter execution was changed.

## What Changed

- Added `scripts/run_product_benchmark.py`.
- The runner calls FastAPI through ASGI and the real `/v1/chat/turn` product
  path.
- It forces product-safe runtime flags:
  - `ALLOW_EVAL_BYPASS=false`
  - `PIPI_EVAL_MODE=false`
  - `LLM_SHADOW_ENABLED=false`
  - `LLM_REWRITE_ENABLED=false`
  - deterministic model/card composer
- It writes:
  - `results.jsonl`
  - `results_guard_report.json`
  - `results_guard_report.md`
  - `quality_report.*`
  - `seed_gap_report.md`
  - `pipi_agent_improvement_report.md`
  - `product_benchmark_summary.*`
- CI quality smoke now runs a 20-case product benchmark instead of coverage-only
  report generation.

## Why

Iterations 9 and 10 made latency and result-row shape part of release quality.
This iteration provides a stable product-path way to generate rows that satisfy
those guards.

## Verification

Commands run:

```bash
cd backend
uv run pytest app/tests/test_product_benchmark_runner.py app/tests/test_results_guard.py app/tests/test_test_scripts.py -q -rx
uv run ruff check ../scripts/run_product_benchmark.py app/tests/test_product_benchmark_runner.py app/eval/results_guard.py app/tests/test_results_guard.py app/tests/test_test_scripts.py
uv run python ../scripts/run_product_benchmark.py --benchmark ../benchmarks/pipi_onsite_500_v1.json --out /tmp/pipi-product-benchmark-smoke --limit 5
uv run pytest -q -rx
uv run alembic heads
uv run alembic current
uv run ruff check app tests ../scripts/run_product_benchmark.py ../scripts/validate_benchmark_results.py
```

Result:

- targeted tests passed.
- product benchmark smoke produced 5 evaluated rows and all 5 had latency data.
- full pytest passed.
- Alembic head/current are both `0009_agent_ability_configs`.
- Ruff passed.

## Follow-Up

- Keep CI smoke thresholds permissive; it proves wiring, not product quality.
- Use the strict gate against full benchmark result rows when available.
