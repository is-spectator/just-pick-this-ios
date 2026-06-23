# Iteration 8 CI Quality Artifact Report

## Scope

This iteration closes the remaining Iteration 7 follow-up: make quality gate
outputs reviewable from CI artifacts.

No iOS code, product routing, recommendation strategy, LLM behavior, or
AbilityCenter execution was changed.

## What Changed

- Updated `.github/workflows/backend-ci.yml` to upload the smoke quality report
  as a GitHub Actions artifact.
- Added a strict quality report artifact upload for checked-in benchmark
  results when `benchmarks/reports/latest/results.jsonl` exists.
- Extended `backend/app/tests/test_test_scripts.py` so CI artifact wiring is
  covered by tests.

## CI Artifacts

The smoke artifact is named:

- `quality-gate-smoke-report`

It includes:

- `quality_gate_report.md`
- `quality_gate_report.json`
- `quality_report.md`
- `quality_report.json`
- `seed_gap_report.md`
- `pipi_agent_improvement_report.md`
- `low_quality_cases.md`
- generated issue markdown files

The strict artifact is named:

- `quality-gate-strict-report`

It is uploaded only when real checked-in benchmark results exist at:

- `benchmarks/reports/latest/results.jsonl`

## Verification

Commands run:

```bash
cd backend
uv run pytest app/tests/test_test_scripts.py app/tests/test_quality_gate.py -q -rx
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

- When live benchmark results are produced in CI, keep strict thresholds on the
  real `results.jsonl` path. Coverage-only smoke remains a wiring check, not a
  product quality signal.
