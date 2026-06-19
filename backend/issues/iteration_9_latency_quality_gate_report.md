# Iteration 9 Latency Quality Gate Report

## Scope

This iteration adds latency thresholds to the existing benchmark quality gate.

No iOS code, product routing, recommendation strategy, LLM behavior, or
AbilityCenter execution was changed.

## What Changed

- Added optional quality gate thresholds:
  - `--max-p50-latency-ms`
  - `--max-p95-latency-ms`
- Quality gate now computes latency stats from evaluated case metadata:
  - `latency_case_count`
  - `p50_latency_ms`
  - `p95_latency_ms`
- If a latency threshold is requested but the report has no `latency_ms` data,
  the gate fails instead of silently passing.
- Strict CI quality gate now uses the north-star latency targets when real
  checked-in benchmark results exist:
  - P50 <= 3500 ms
  - P95 <= 6000 ms
- Coverage-only smoke reports intentionally do not enable latency thresholds.
- README documents latency gate behavior.

## Why

Functional pass rate is not enough for Pipi. A route can be correct but still
feel broken if the turn takes too long. This gate makes latency a release
quality signal when real benchmark result rows are available.

## Verification

Commands run:

```bash
cd backend
uv run pytest app/tests/test_quality_gate.py app/tests/test_test_scripts.py -q -rx
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

- Ensure any live benchmark runner writes `latency_ms` for every evaluated row.
- Keep coverage-only report generation separate from release-quality latency
  gating.
