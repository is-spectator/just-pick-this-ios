# Iteration 6 Quality Gate Report

## Scope

This iteration adds a release-quality gate on top of the existing benchmark quality reports.

No iOS code, product routing, recommendation strategy, LLM behavior, or AbilityCenter execution was changed.

## What Changed

- Added `app.eval.quality_gate`.
- Added CLI wrapper `scripts/quality_gate.py`.
- Added tests in `app/tests/test_quality_gate.py`.
- Updated `backend/README.md` with quality gate usage.

## Gate Inputs

The gate reads an existing report directory containing:

- `quality_report.json`
- optional `shadow_comparison_report.json`

It writes:

- `quality_gate_report.json`
- `quality_gate_report.md`

## Default Gate Policy

The CLI defaults are intentionally strict:

- `min_pass_rate = 0.95`
- `min_average_quality = 0.82`
- `max_p0 = 0`
- `max_p1 = 0`

Optional shadow gate:

- `--min-shadow-schema-valid-rate 0.98`
- provider errors must be `0`
- timeouts must be `0`

## What It Blocks

- P0 cases:
  - response kind mismatch
  - location state mismatch
  - target type mismatch
  - wrong tool call
  - missing required recommendation/help-card payload
- P1 cases:
  - seed gaps
  - failed cases not classified as P0
- Threshold failures:
  - pass rate below target
  - average quality below target
  - shadow schema-valid rate below target

## Why This Matters

Iteration 5 generated actionable issues. Iteration 6 makes those issues enforceable:

```text
benchmark results
-> quality reports
-> generated issues
-> quality gate
-> pass/fail signal for release or next repair iteration
```

This prevents "report-only" regressions where P0/P1 failures are visible but not blocking.

## Verification

Commands run from `backend/`:

```bash
uv run pytest app/tests/test_quality_gate.py app/tests/test_quality_report_generation.py app/tests/test_test_scripts.py -q -rx
```

Result:

- targeted tests passed.

Full verification should run:

```bash
uv run pytest -q -rx
uv run alembic heads
uv run alembic current
uv run ruff check app tests
```

## Usage

After generating benchmark reports:

```bash
uv run python ../scripts/quality_gate.py \
  --report-dir ../benchmarks/reports/latest \
  --min-pass-rate 0.95 \
  --min-average-quality 0.82 \
  --max-p0 0 \
  --max-p1 0
```

For shadow runs:

```bash
uv run python ../scripts/quality_gate.py \
  --report-dir ../benchmarks/reports/latest \
  --min-shadow-schema-valid-rate 0.98
```

## Follow-Up

- Wire `scripts/quality_gate.py` into CI after live benchmark result generation.
- Keep coverage-only report generation non-blocking unless a results JSONL is present.
- Use generated P0/P1 issue files as the next repair backlog.
