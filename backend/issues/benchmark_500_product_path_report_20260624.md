# ISS-010 Benchmark 500 Product Path Report 2026-06-24

## Scope

This closes the explicit reporting gap for **ISS-010: 500 条 benchmark 结构化扩容并跑 product path**.

The benchmark suite and product runner already existed. This slice makes the product benchmark summary itself prove the suite identity, target count, category coverage, evaluated coverage, and required runtime path.

## Existing Foundation

- `benchmarks/pipi_onsite_500_v1.json`
- `backend/app/tests/test_benchmark_500_distribution.py`
- `scripts/run_product_benchmark.py`
- `backend/app/tests/test_product_benchmark_runner.py`
- `backend/app/tests/test_product_benchmark_runtime_gate.py`

## Added

`scripts/run_product_benchmark.py` now writes `benchmark_coverage` into:

- `product_benchmark_summary.json`
- `product_benchmark_summary.md`
- `latest.json`

The coverage block includes:

- `suite_id`
- `target_case_count`
- `case_count`
- `evaluated_case_count`
- `is_limited_run`
- `coverage_complete`
- `runtime_path_required=product`
- `by_category`
- `evaluated_by_category`
- `expected_distribution`

## Why This Matters

ISS-010 should not depend on someone manually opening the benchmark JSON and then separately inspecting runtime rows. The summary now ties both together:

1. The suite is the structured 500-case suite.
2. The evaluated rows are product-path rows.
3. Limited smoke runs are clearly marked as limited and do not pretend to be full coverage.

## Non-goals

- No benchmark cases were changed.
- No routing or recommendation behavior changed.
- No iOS changes were made.
- No LLM or shadow mode changes were made.
