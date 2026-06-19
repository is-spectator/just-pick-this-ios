# Iteration 3 Shadow Mode Live Report

## Scope

Completed Iteration 3: LLM Shadow Mode live loop.

This iteration keeps the product runtime deterministic. Shadow LLM decisions are recorded only for trace/eval comparison and do not execute tools, create cards, or change `/v1/chat/turn` responses.

## Changes

- Added `scripts/run_shadow_benchmark.py`.
  - Runs local FastAPI ASGI product turns through `/v1/bootstrap` and `/v1/chat/turn`.
  - Forces product path with `ALLOW_EVAL_BYPASS=false` and `PIPI_EVAL_MODE=false`.
  - Enables shadow mode with `LLM_SHADOW_ENABLED=true`.
  - Supports `--shadow-provider mock_shadow | openai`.
  - Writes `shadow_results.jsonl`.
  - Calls `benchmark_quality_report.py` programmatically to generate quality, seed-gap, agent-improvement, and shadow comparison reports.
  - Fails if the written results do not contain shadow events or if the shadow schema-valid rate is below threshold.

- Added `backend/app/tests/test_shadow_benchmark_runner.py`.
  - Verifies mock shadow benchmark writes non-empty `shadow_results.jsonl`.
  - Verifies non-empty `shadow_decisions.jsonl`.
  - Verifies shadow schema-valid rate is `1.0` for `mock_shadow`.
  - Verifies product output and product tool calls remain deterministic.
  - Verifies the shadow gate rejects missing shadow events and provider/timeout failures.

- Hardened `backend/app/tests/test_shadow_mode.py`.
  - Missing OpenAI key now asserts no HTTP client is constructed.

## Shadow Gate

The shadow benchmark gate checks:

- `total_cases`
- `shadow_enabled_cases`
- `shadow_success`
- `shadow_schema_errors`
- `shadow_provider_errors`
- `shadow_timeouts`
- `shadow_schema_valid_rate`
- `decision_mismatch_count`

Default threshold: `shadow_schema_valid_rate >= 0.98`.

`mock_shadow` currently passes with `1.0`.

## Live Check

Command:

```bash
cd backend
uv run python ../scripts/run_shadow_benchmark.py \
  --benchmark ../benchmarks/pipi_onsite_500_v1.json \
  --out /tmp/pipi-shadow-live-check \
  --limit 20 \
  --shadow-provider mock_shadow
```

Result:

```text
evaluated_cases: 20
skipped_expected_direct_cases: 50
skipped_without_shadow_cases: 4
shadow_enabled_cases: 20
shadow_schema_valid_rate: 1.0
shadow_schema_errors: 0
shadow_provider_errors: 0
shadow_timeouts: 0
decision_mismatch_count: 0
```

Generated files:

- `/tmp/pipi-shadow-live-check/shadow_results.jsonl`: 20 rows
- `/tmp/pipi-shadow-live-check/shadow_decisions.jsonl`: 20 rows
- `/tmp/pipi-shadow-live-check/shadow_comparison_report.md`
- `/tmp/pipi-shadow-live-check/shadow_comparison_report.json`
- `/tmp/pipi-shadow-live-check/quality_report.md`
- `/tmp/pipi-shadow-live-check/seed_gap_report.md`
- `/tmp/pipi-shadow-live-check/pipi_agent_improvement_report.md`

## Product Behavior

Product output remains deterministic:

- Shadow does not call AbilityCenter.
- Shadow does not create RecommendationCard.
- Shadow does not create HelpCard.
- Shadow schema/provider/timeout errors remain trace-only and do not break `/v1/chat/turn`.

## Observation

During the 20-case live check, 4 benchmark cases were skipped after product response because they were expected product cases but the current InputGate returned clarification and therefore did not enter PipiLoop/shadow.

Examples include:

- `我在北京鼓楼，想吃川菜，你直接帮我选一个`
- `我在北京亮马桥，想吃火锅，你直接帮我选一个`

This is a route/slot extraction quality issue for later routing work. It is intentionally not fixed in this shadow-mode iteration.

## Verification

Commands run:

```bash
cd backend
uv run pytest app/tests/test_shadow_benchmark_runner.py app/tests/test_shadow_mode.py -q -rx
uv run pytest -q -rx
uv run alembic heads
uv run alembic current
uv run ruff check app tests
uv run python ../scripts/run_shadow_benchmark.py \
  --benchmark ../benchmarks/pipi_onsite_500_v1.json \
  --out /tmp/pipi-shadow-live-check \
  --limit 20 \
  --shadow-provider mock_shadow
```

Results:

- Targeted shadow tests: passed.
- Full pytest: passed.
- Alembic heads/current: passed at `0007_agent_prompt_configs`.
- Ruff: passed.
- Shadow benchmark live check: passed.

## Next Steps

- Run a small OpenAI shadow batch with an explicit `OPENAI_API_KEY` and `--shadow-provider openai`.
- Add a separate routing follow-up for `鼓楼` and `亮马桥` area extraction if those cases should enter product loop.
- Keep `LLM_SHADOW_ENABLED=false` by default until shadow report stability is proven over larger benchmark batches.
