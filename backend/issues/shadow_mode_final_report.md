# LLM Shadow Mode Final QA Report

Date: 2026-05-27
Role: Agent 6 - Coordinator QA

## Executive Summary

Final acceptance status: pass for LLM shadow-mode preparation, product deterministic runtime protection, and admin trace readability.

The final full regression run passed, Alembic is at the single current head, Ruff passed, and the requested benchmark report artifacts were generated. Shadow mode remains default-off and audit-only. Product decisions, tool calls, UI events, cards, and help cards continue to be driven by the deterministic path.

One important limitation remains: the requested benchmark command did not include `--results`, so it generated coverage and empty quality/shadow comparison outputs from the 500-case benchmark definition. This still satisfies this round's report-generation check, but it is not a live 500-case product-vs-shadow execution.

## Required Checks

| Check | Result | Evidence |
| --- | --- | --- |
| 1. Shadow mode default off | Pass | `app/config.py` defaults `llm_shadow_enabled=False` and `llm_provider="none"`. `test_shadow_disabled_by_default_keeps_datong_product_path` asserts no `shadow_reasoner_result` appears when disabled. |
| 2. Product deterministic path unchanged | Pass | `app/services/chat.py` still records `model_provider=settings.pipi_model_provider` with deterministic default and constructs `PipiLoop` with deterministic product execution. Shadow is injected only when `settings.llm_shadow_enabled` is true. Shadow tests assert Datong product output and deterministic tool sequence stay unchanged. |
| 3. Shadow does not call tools | Pass | `PipiLoop._run_shadow_reasoner` calls only `shadow_reasoner.run_shadow(...)`; actual tool execution remains `ability_center.call(decision.tool_name, ...)` for the deterministic decision. `test_shadow_does_not_add_tool_calls_or_persist_cards` confirms persisted `ToolCall` count equals the deterministic sequence only. |
| 4. Shadow does not write cards | Pass | Shadow result is appended to trace/state as `shadow_reasoner_result` / `shadow_summary`. Card persistence remains owned by product tool execution. `test_shadow_does_not_add_tool_calls_or_persist_cards` confirms only one product recommendation card and zero shadow-created help cards for the Datong case. |
| 5. Shadow schema error does not affect product | Pass | `ShadowReasoner` returns `status="schema_error"` for invalid provider output. `test_mock_shadow_schema_error_does_not_affect_datong_product_path` asserts `/v1/chat/turn` still returns the normal Datong product card path and records schema errors in shadow summary. |
| 6. Admin trace can see shadow | Pass | `app/debug/routes.py` exposes `shadow_summary`, `shadow_events`, and `shadow_decision_diffs` in trace detail. `test_admin_trace_detail_exposes_shadow_runtime_fields` verifies a trace shows shadow event data and decision diffs. |
| 7. Tests result | Pass on final full run | Initial `uv run pytest -q -rx` produced transient failures in admin prompt audit ordering and eval reset stale-data paths. Targeted rerun passed, and a second full `uv run pytest -q -rx` passed. |

## Command Results

| Command | Exit | Result |
| --- | ---: | --- |
| `uv run pytest -q -rx` | 1 then 0 | First full run failed transiently; failing cases passed in targeted rerun; second full run passed. Final acceptance run is green. |
| `uv run alembic heads` | 0 | `0007_agent_prompt_configs (head)` |
| `uv run alembic current` | 0 | Current DB is `0007_agent_prompt_configs (head)` |
| `uv run ruff check app tests` | 0 | `All checks passed!` |
| `uv run python ../scripts/benchmark_quality_report.py --benchmark ../benchmarks/pipi_onsite_500_v1.json --out /tmp/pipi-shadow-check` | 0 | Report files generated under `/tmp/pipi-shadow-check`. |
| Targeted shadow/admin/report pytest | 0 | `app/tests/test_shadow_mode.py`, admin shadow trace test, and shadow comparison report generation test passed: 7 passed. |

## Generated Benchmark Artifacts

All requested files were generated:

- `/tmp/pipi-shadow-check/quality_report.md`
- `/tmp/pipi-shadow-check/seed_gap_report.md`
- `/tmp/pipi-shadow-check/pipi_agent_improvement_report.md`
- `/tmp/pipi-shadow-check/shadow_comparison_report.md`
- `/tmp/pipi-shadow-check/shadow_decisions.jsonl`

Observed artifact contents:

- Benchmark coverage is valid for 500 cases.
- `quality_report.md` shows `Total = 0`.
- `shadow_comparison_report.md` shows `Total cases with shadow = 0`.
- `shadow_decisions.jsonl` exists but has 0 lines.

Reason: `scripts/benchmark_quality_report.py` writes empty result reports when `--results` is omitted and only `--benchmark` is supplied.

## Runtime Protection Assessment

The product runtime is still protected by three boundaries:

1. Default config keeps shadow off unless `LLM_SHADOW_ENABLED=true`.
2. Product path still uses deterministic reasoner decisions to execute tools.
3. Shadow output is stored only in audit trace/state fields and is not converted into `ToolCall`, `RecommendationCard`, `HelpCard`, UI events, or final answers.

The most relevant regression tests are:

- `test_shadow_disabled_by_default_keeps_datong_product_path`
- `test_mock_shadow_keeps_datong_product_output_and_records_shadow_result`
- `test_mock_shadow_schema_error_does_not_affect_datong_product_path`
- `test_shadow_decision_mismatch_is_recorded_without_changing_korea_ui_events`
- `test_shadow_does_not_add_tool_calls_or_persist_cards`
- `test_admin_trace_detail_exposes_shadow_runtime_fields`
- `test_quality_report_generates_shadow_comparison_files`

## Unfinished Items

1. Real OpenAI shadow provider is not implemented yet; current providers are `mock_shadow`, `mock_shadow_schema_error`, and unsupported-provider error behavior.
2. The benchmark command in this QA pass did not execute live product turns or live shadow calls. A real shadow comparison run needs a result JSON/JSONL passed via `--results`.
3. The first full pytest run exposed a non-reproduced state/order-sensitive failure pattern. Final rerun passed, but eval reset/admin audit isolation should stay on the watch list.
4. No sampling/cost controls were verified in this pass beyond default-off behavior.

## Recommendations Before Connecting Real LLM

1. Implement the `openai` branch in `ShadowReasoner._call_provider` with strict structured output and the existing `ShadowReasonerResult` validation boundary.
2. Keep real LLM shadow behind `LLM_SHADOW_ENABLED=true`, `LLM_PROVIDER=openai`, and explicit API-key presence checks.
3. Add sample-rate and max-calls guards before any broad benchmark or staging run.
4. Add provider timeout, provider error, invalid JSON, and invalid schema tests using monkeypatched clients.
5. Produce a real shadow run JSONL from `/v1/chat/turn` executions, then rerun `benchmark_quality_report.py --results <run.jsonl> --benchmark ../benchmarks/pipi_onsite_500_v1.json --out <dir>`.
6. Promote admin trace fields into the QA dashboard only after confirming large trace payloads stay readable and do not expose secrets.
