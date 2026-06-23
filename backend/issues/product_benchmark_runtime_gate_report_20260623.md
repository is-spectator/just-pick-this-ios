# ISS-001 Product Benchmark Runtime Gate Report

## Scope

This slice tightens the existing product benchmark runner so runtime failures are explicit and machine-gated.

## Changes

- `scripts/run_product_benchmark.py` now computes a `runtime_gate` for every run.
- The gate fails when any evaluated row is not a clean product-path response.
- Failure samples include:
  - `case_id`
  - category
  - row status
  - HTTP status
  - runtime path
  - issue codes
- `product_benchmark_summary.json`, `product_benchmark_summary.md`, and `latest.json` now expose the runtime gate.
- The CLI exits non-zero after writing reports if the runtime gate fails.

## Product Path Contract

A row is runtime-clean only when:

- HTTP status is 200
- `response.metadata.runtime_path == "product"`
- row `status == "passed"`
- no runtime issues are attached

Quality mismatches still belong to the quality reports; this gate is specifically for benchmark execution correctness and bypass prevention.

## Verification

- Added no-DB runtime gate tests for clean product rows and eval-bypass failures.
- Existing product benchmark readiness and result guard tests continue to pass.

