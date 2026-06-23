# Iteration 7 CI Quality Gate Wiring Report

## Scope

This iteration wires the Iteration 6 quality gate into scripts and CI.

No iOS code, product routing, recommendation strategy, LLM behavior, or AbilityCenter execution was changed.

## What Changed

- Added `scripts/test_quality_gate.sh`.
- Added quality-gate tests to `scripts/test_unit.sh`.
- Added CI smoke steps to `.github/workflows/backend-ci.yml`.
- Added optional strict CI gate when `benchmarks/reports/latest/results.jsonl` exists.
- Updated `backend/README.md`.
- Extended script/workflow tests in `app/tests/test_test_scripts.py`.

## CI Behavior

The workflow now runs:

1. Full backend tests.
2. Ruff.
3. Benchmark report coverage smoke.
4. Quality gate smoke with permissive thresholds:
   - `min_pass_rate=0`
   - `min_average_quality=0`
   - `max_p0=0`
   - `max_p1=0`
5. Strict gate only when checked-in benchmark results exist:
   - `benchmarks/reports/latest/results.jsonl`
   - `min_pass_rate=0.95`
   - `min_average_quality=0.82`
   - `max_p0=0`
   - `max_p1=0`

## Important Boundary

Coverage-only reports are not treated as proof of product quality. They only verify:

- benchmark schema can be read;
- report files can be generated;
- generated issue artifacts are produced;
- quality gate CLI can run.

Strict quality gating requires real evaluated results JSONL.

## Local Commands

No-DB smoke:

```bash
./scripts/test_quality_gate.sh
```

Strict gate after a real benchmark run:

```bash
cd backend
uv run python ../scripts/benchmark_quality_report.py \
  --results ../benchmarks/reports/latest/results.jsonl \
  --benchmark ../benchmarks/pipi_onsite_500_v1.json \
  --out ../benchmarks/reports/latest

uv run python ../scripts/quality_gate.py \
  --report-dir ../benchmarks/reports/latest \
  --min-pass-rate 0.95 \
  --min-average-quality 0.82 \
  --max-p0 0 \
  --max-p1 0
```

## Verification

Commands run:

```bash
cd backend
uv run pytest app/tests/test_test_scripts.py app/tests/test_quality_gate.py -q -rx
../scripts/test_quality_gate.sh
uv run alembic upgrade head
uv run pytest -q -rx
uv run alembic heads
uv run alembic current
uv run ruff check app tests
```

Result:

- targeted tests passed.
- report/gate smoke generated `quality_gate_report.json` and `quality_gate_report.md`.
- database schema upgraded to `0009_agent_ability_configs`.
- full pytest passed.
- Alembic head/current are both `0009_agent_ability_configs`.
- Ruff passed.

Note: the first full pytest run exposed a local schema drift where `agent_ability_configs`
was missing. Running `uv run alembic upgrade head` fixed the local database and the
rerun passed.

## Follow-Up

- Add a job that uploads `quality_gate_report.md` as a CI artifact once benchmark result JSONL is produced.
- Keep live benchmark execution separate from coverage-only smoke to avoid mistaking schema checks for product quality.
