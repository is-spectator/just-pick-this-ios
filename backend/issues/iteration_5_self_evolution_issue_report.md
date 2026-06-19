# Iteration 5 Self-Evolution Issue Generation Report

## Scope

This iteration completes `docs/pipi-agent-iteration-plan.md` Iteration 5: benchmark reports now generate executable markdown issues.

No product routing, iOS UI, recommendation strategy, LLM behavior, or AbilityCenter execution was changed.

## What Changed

- `write_quality_reports(...)` now also writes generated issue artifacts under the report output directory:
  - `generated/index.md`
  - `generated/issuer_000.md`, `generated/issuer_001.md`, ... for individual P0/P1 issues
  - `generated/p2_aggregate.md` for lower-priority degraded cases
- Added issue rendering from `CaseQualityScore` with:
  - priority: `P0`, `P1`, `P2`
  - owner: `router`, `data_seed`, `evidence`, `tool`, `help_card`, `card_contract`, `runtime`, or `agent`
  - bucket: `seed_gap` or `agent_improvement`
  - trace/agent/retrieval ids when present
  - reproduction notes
  - fix scope
  - forbidden changes
  - suggested tests
  - acceptance criteria
- `quality_report.json` / `case_quality_scores.jsonl` case metadata now includes:
  - `trace_id`
  - `agent_run_id`
  - `retrieval_run_id`

## Classification Rules

- `seed_gap` remains strictly:
  - expected `recommendation_card`
  - actual `help_card_draft`
- `agent_improvement` excludes seed-gap fallback cases.
- P0 examples:
  - `response_kind_mismatch`
  - `location_state_mismatch`
  - `target_type_mismatch`
  - `tool_call_name_mismatch`
  - missing required card/help-card payloads
- P1 examples:
  - seed gaps
  - failed cases not in the P0 set
- P2:
  - degraded/warning-only cases, aggregated instead of generating noisy per-case tickets

## Why This Matters

The self-evolution loop now turns benchmark output into an actionable backlog:

```text
benchmark results
-> quality scores
-> seed_gap / agent_improvement split
-> generated executable issues
-> owner-specific fix scope and tests
```

This prevents common bad triage:

- wrong recommendations are not filed as seed gaps;
- missing data is not fixed by loosening router/evaluator behavior;
- P2 noise does not create dozens of low-signal tickets.

## Verification

Commands run from `backend/`:

```bash
uv run pytest app/tests/test_quality_report_generation.py app/tests/test_benchmark_non_empty_guard.py app/tests/test_quality_scoring.py -q -rx
uv run python ../scripts/benchmark_quality_report.py --benchmark ../benchmarks/pipi_onsite_500_v1.json --out /tmp/pipi-iteration5-coverage-check
uv run pytest -q -rx
uv run alembic heads
uv run alembic current
uv run ruff check app tests
```

Result:

- Targeted reporting tests passed.
- Coverage-only report generated `generated/index.md` and `generated/p2_aggregate.md`.
- Full pytest passed.
- Alembic heads/current passed.
- Ruff passed.

## Follow-Up

- When real benchmark result JSONL is available, run:

```bash
uv run python ../scripts/benchmark_quality_report.py \
  --benchmark ../benchmarks/pipi_onsite_500_v1.json \
  --results <results.jsonl> \
  --out <report_dir>
```

- Review `<report_dir>/generated/index.md` first.
- Fix P0 issues before P1.
- Treat `data_seed` issues as data work unless trace proves router/evidence failure.
