# ISS-026 Runtime Latency Summary Slice

## Scope

This slice extends the previous cost/latency timeout guard with a read-only runtime latency summary. It does not change `/v1/chat/turn`, recommendation strategy, tool execution, or iOS.

## What Changed

- Added `app.services.runtime_latency`.
- Added admin endpoint:
  - `GET /admin/api/runtime-latency?hours=24&limit=500`
- Added latency summaries for:
  - `agent_runs`
  - `tool_calls`
  - `retrieval_runs`
- Added p50/p95/max, slow counts, failure counts, status counts, by-group breakdown, and slowest rows.
- Added markdown renderer for report reuse.
- Added no-DB tests for summary and markdown rendering.

## Admin Endpoint

The endpoint uses existing admin auth and writes an `admin_audit_logs` row with action `view_runtime_latency`.

Response includes:

- `window`
- `agent_runs`
- `tool_calls`
- `retrieval_runs`
- `slowest`
- `cost`
- `metadata.slow_thresholds_ms`

## Cost Tracking Status

The current product path is deterministic. This report intentionally returns:

```json
{
  "estimated_cost_usd": null,
  "tracking_status": "not_available_until_llm_provider_costs"
}
```

Real provider/token cost should be added only when product LLM execution is promoted beyond guarded or shadow paths.

## Follow-ups

1. Persist per-provider token usage for product LLM calls.
2. Add per-tool budget overrides for search, route planning, finalizer, and model calls.
3. Surface this summary in the admin HTML dashboard.
4. Connect latency regressions to the quality gate as a release blocker.

