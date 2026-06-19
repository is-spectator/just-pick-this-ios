# Iteration 12 Product Benchmark Summary Report

## Scope

This iteration improves the product benchmark runner summary so latency and
runtime distribution are visible without manually inspecting `results.jsonl`.

No iOS code, product routing, recommendation strategy, LLM behavior, or
AbilityCenter execution was changed.

## What Changed

- `scripts/run_product_benchmark.py` now writes summary stats into
  `product_benchmark_summary.json` and `.md`:
  - latency count;
  - P50 latency;
  - P95 latency;
  - max latency;
  - status code counts;
  - response kind counts;
  - runtime path counts;
  - slowest 10 cases.
- Existing `results.jsonl`, results guard, and quality reports are unchanged.
- Tests now assert the summary contains latency stats, response kind counts,
  runtime path counts, and slowest cases.

## Why

The release gate can now enforce latency thresholds, but humans still need a
quick way to see which cases are slow from CI artifacts. This summary makes the
product benchmark smoke artifact immediately useful.

## Verification

Commands run:

```bash
cd backend
uv run pytest app/tests/test_product_benchmark_runner.py -q -rx
uv run ruff check ../scripts/run_product_benchmark.py app/tests/test_product_benchmark_runner.py
uv run python ../scripts/run_product_benchmark.py --benchmark ../benchmarks/pipi_onsite_500_v1.json --out /tmp/pipi-product-benchmark-stats --limit 5
uv run pytest -q -rx
uv run alembic heads
uv run alembic current
uv run ruff check app tests ../scripts/run_product_benchmark.py
```

Result:

- targeted tests passed.
- product benchmark smoke produced latency summary and slowest-case table.
- full pytest passed.
- Alembic head/current are both `0009_agent_ability_configs`.
- Ruff passed.

## Follow-Up

- If CI begins running larger product benchmark samples, keep
  `product_benchmark_summary.md` in the uploaded artifact set for quick review.
