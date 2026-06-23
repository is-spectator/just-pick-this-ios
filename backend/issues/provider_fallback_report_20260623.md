# Provider Fallback Report - 2026-06-23

## Scope

This slice addresses ISS-027: provider fallback hardening for the product reasoner path.

The default product runtime remains deterministic. When `PIPI_MODEL_PROVIDER=openai` is explicitly enabled, the OpenAI reasoner must stay inside the PipiLoop contract and degrade to the deterministic baseline on provider, timeout, or schema failures.

## Changes

- `OpenAIReasoner` now annotates fallback decisions with:
  - `llm_fallback=true`
  - `llm_error_type=disabled | schema_error | provider_error | timeout`
  - bounded `llm_error`
- `PipiLoop` records a dedicated `reasoner_provider_fallback` trace event whenever a product LLM decision falls back or is disabled.
- `PipiLoopResult.state` now includes:
  - `reasoner_provider_fallbacks`
  - `reasoner_provider_fallback_summary`
- `/v1/chat/turn` loop metadata exposes the summary under:
  - `metadata.loop.reasoner_provider_fallback`

## Product Safety

- Fallback does not call additional tools.
- Fallback does not create RecommendationCard or HelpCard records.
- Fallback uses the deterministic baseline decision already produced before the provider call.
- Provider/schema failures do not change `ui_events`, `tool_calls`, or final product output.

## Tests

- `test_provider_fallback.py`
  - missing OpenAI key returns deterministic decision annotated as disabled
  - provider error records `reasoner_provider_fallback` and keeps product output unchanged
- `test_openai_product_reasoner.py`
  - invalid OpenAI schema still completes the product tool loop
  - product AgentRun trace includes `reasoner_provider_fallback`
  - response metadata includes fallback summary

## Notes

This does not promote LLM decisions. It only makes product provider failure observable and safe when OpenAI product mode is explicitly configured.
