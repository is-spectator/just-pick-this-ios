# Provider Fallback Metrics Report - 2026-06-24

## Scope

This slice tightens ISS-027 provider fallback observability without changing the LLM rollout strategy.

Existing behavior already keeps product output safe:

- `OpenAIReasoner` falls back to deterministic decisions when the provider is disabled, errors, times out, or returns invalid schema.
- `PipiLoop` records `reasoner_provider_fallback` trace events.
- Product cards/tool calls remain driven by the guarded deterministic/tool contract.

## Changes

`reasoner_provider_fallback_summary` now exposes release-facing rates:

- `fallback_rate`
- `schema_error_rate`
- `provider_error_rate`
- `timeout_rate`

These are derived from the already-recorded fallback events and are surfaced in the same `metadata.loop.reasoner_provider_fallback` payload used by product/admin traces.

## Validation

Focused tests cover:

- provider error fallback rate;
- schema error fallback rate;
- product output/tool calls remaining unchanged.

Commands:

```bash
uv run --extra dev pytest app/tests/test_provider_fallback.py app/tests/test_openai_product_reasoner.py -q -rx
```

