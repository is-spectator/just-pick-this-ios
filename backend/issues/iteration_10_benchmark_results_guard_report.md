# Iteration 10 Benchmark Results Guard Report

## Scope

This iteration adds a preflight guard for evaluated benchmark result files.

No iOS code, product routing, recommendation strategy, LLM behavior, or
AbilityCenter execution was changed.

## What Changed

- Added `backend/app/eval/results_guard.py`.
- Added CLI wrapper `scripts/validate_benchmark_results.py`.
- Strict CI quality gate now validates `benchmarks/reports/latest/results.jsonl`
  before report generation.
- Strict CI requires latency data in real benchmark result rows.
- Strict CI artifacts now include:
  - `results_guard_report.md`
  - `results_guard_report.json`
- README documents the results guard before release-quality gating.

## Guard Rules

The guard requires:

- result file is a JSON array or JSONL rows;
- at least one evaluated row exists;
- each row has a case id;
- each row has a user message/input;
- each row has either a response object or status code;
- when `--require-latency-ms` is passed, each row has parseable `latency_ms`.

## Why

Iteration 9 made latency part of release quality. This iteration prevents
missing or malformed benchmark results from silently producing misleading
quality reports.

## Verification

Commands run:

```bash
cd backend
uv run pytest app/tests/test_results_guard.py app/tests/test_test_scripts.py app/tests/test_quality_gate.py -q -rx
../scripts/test_quality_gate.sh
uv run pytest -q -rx
uv run alembic heads
uv run alembic current
uv run ruff check app tests
```

Result:

- targeted tests passed.
- quality gate smoke script passed.
- full pytest passed.
- Alembic head/current are both `0009_agent_ability_configs`.
- Ruff passed.

## Follow-Up

- When a live benchmark runner is added for non-shadow product turns, make it
  write `latency_ms` for every evaluated row and run this guard before report
  generation.
