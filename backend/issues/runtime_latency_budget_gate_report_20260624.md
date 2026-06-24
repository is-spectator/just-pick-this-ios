# Runtime Latency Budget Gate Report - 2026-06-24

## Scope

This slice hardens **ISS-026 Cost/Latency**.

Earlier work added tool-call timeout protection and runtime latency summaries. The remaining gap was that the product runtime summary did not explicitly answer the acceptance question: whether P95 stays inside the target budget.

## Changes

- `summarize_runtime_latency(...)` now includes `latency_budget`.
- `GET /admin/api/runtime-latency` inherits the same budget payload because it returns the service summary.
- `render_runtime_latency_markdown(...)` now renders a `Latency Budget` section.

## Budget Fields

`latency_budget` includes:

- `agent_p95_target_ms`
- `tool_p95_target_ms`
- `retrieval_p95_target_ms`
- `agent_p95_ms`
- `tool_p95_ms`
- `retrieval_p95_ms`
- `agent_p95_target_met`
- `tool_p95_target_met`
- `retrieval_p95_target_met`
- `overall_target_met`
- `slow_total`
- `failure_total`

## Validation

Updated `backend/app/tests/test_runtime_latency.py` to verify:

- agent/tool/retrieval P95 target checks;
- `overall_target_met` behavior;
- slow/failure totals;
- Markdown renders the new `Latency Budget` section.

## Notes

- This does not change runtime behavior.
- This does not change timeout values.
- Cost remains marked as unavailable until token-producing product LLM mode is promoted.
