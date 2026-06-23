# Cost / Latency Budget Report - 2026-06-23

## Scope

This slice addresses the first backend-only runtime guard for ISS-026: per-tool latency budget and graceful timeout degradation.

Existing benchmark/reporting code already tracks turn latency, P50/P95 gates, and result-row latency coverage. This change adds the missing runtime boundary: PipiLoop now protects AbilityCenter tool calls with a configurable timeout.

## Change

- Added `PIPI_TOOL_TIMEOUT_SECONDS`, default `8.0`.
- `PipiLoop` now wraps each `AbilityCenter.call(...)` in the configured timeout budget.
- If a tool times out, PipiLoop converts it into a standard `ToolResult`:
  - `ok=false`
  - `status="unavailable"`
  - `data.timeout=true`
  - `data.timeout_seconds=<configured budget>`
  - `error_message="<tool> timed out after ... seconds"`
- The failed ToolResult still flows through:
  - `tool_result` trace event
  - Evaluator
  - next Reasoner turn
  - final safe answer

## Product Safety

- Timeout does not bypass PipiLoop.
- Timeout does not create cards.
- Timeout does not skip evaluator/answer gate.
- Timeout does not require changes to individual tools.

## Tests

- `test_pipi_loop_tool_timeout_returns_failed_tool_result`
  - simulates a slow ability tool
  - verifies PipiLoop returns a normal answer
  - verifies timeout metadata is present in the `tool_result` trace

## Follow-ups

- Add per-tool override budgets if real production telemetry shows different needs for search, AMap, finalizer, and model calls.
- Add cost estimation for actual token-producing providers once product LLM mode is promoted beyond guarded/shadow operation.
