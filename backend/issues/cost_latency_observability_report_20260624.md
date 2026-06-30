# Cost / Latency Observability Report - 2026-06-24

## Scope

This slice closes the remaining ISS-026 observability gap.

Existing work already added:

- PipiLoop per-tool timeout protection.
- Runtime P50/P95 summaries for agent runs, tool calls, and retrieval runs.
- A latency budget payload with the 1.5s product P95 target.

The missing piece from the issue sheet was an explicit `cost_per_turn` metric and timeout counting from runtime payloads.

## Changes

- `summarize_runtime_latency(...)` now extracts cost from runtime JSON payloads when providers or tools emit:
  - `cost_usd`
  - `estimated_cost_usd`
  - `total_cost_usd`
- Runtime cost summary now includes:
  - `tracking_status`
  - `estimated_cost_usd`
  - `cost_per_turn_usd`
  - `rows_with_cost`
  - `source_counts`
- Runtime group summaries now count timeout payloads in addition to `status="timeout"`.
- `latency_budget.timeout_total` is now surfaced for admin/report consumers.
- Markdown output now renders `Cost per turn` and `Rows with cost`.

## Product Safety

- No request-path behavior changed.
- No timeout values changed.
- Missing cost data remains non-fatal and is reported as `not_available_until_llm_provider_costs`.
- Tool timeouts continue to return a failed `ToolResult` that flows through evaluator and answer gate, so product responses remain available.

## Validation

Focused test:

```bash
uv run --extra dev pytest app/tests/test_runtime_latency.py -q -rx
```

Result: passed.

