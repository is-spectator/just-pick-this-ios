# Iteration 4 LLM Query Rewrite Report

## Scope

This iteration implements the next step in `docs/pipi-agent-iteration-plan.md`: a gated LLM query rewrite layer before InputGate.

It does not change iOS, product recommendation strategy, AbilityCenter execution, or card/help-card creation semantics.

## What Changed

- Added `LLM_REWRITE_ENABLED=false` and `LLM_REWRITE_MIN_CONFIDENCE=0.78`.
- Added `app.services.llm_query_rewrite` with:
  - deterministic-safe `mock_shadow` provider support;
  - optional OpenAI provider support;
  - schema validation;
  - timeout/provider/schema error handling;
  - deterministic-slot-first merge policy.
- `/v1/chat/turn` now computes:
  - deterministic rewrite;
  - optional LLM rewrite candidate;
  - selected rewrite result.
- InputGate can accept a precomputed rewrite result.
- Product trace records `query_rewrite_result` when LLM rewrite is enabled.
- Response metadata includes query rewrite selection details for eval/admin attribution.

## Safety Rules

- Default is off: `LLM_REWRITE_ENABLED=false`.
- LLM rewrite never calls AbilityCenter.
- LLM rewrite never creates `RecommendationCard` or `HelpCard`.
- LLM rewrite only fills missing slots; deterministic slots win conflicts.
- Low-confidence, schema-error, provider-error, timeout, and missing-key cases fall back to deterministic rewrite.
- Product output remains controlled by PipiLoop + AbilityCenter + Evaluator + AnswerGate.

## Regression Fixed During This Iteration

The first full-suite run exposed a product-path regression: the graph-level InputGate rewrite used method `input_gate`, which made `DbPipiAbilityCenter` skip the richer deterministic adapter rewrite. This weakened AMap, venue-ordering, Tavily reference image, and contextual session flows.

Fix:

- Graph-level query rewrite now uses method `deterministic_input_gate`, allowing the DB-backed AbilityCenter to merge InputGate slots with the richer deterministic product rewrite before tool execution.

## Tests Added

- `app/tests/test_llm_query_rewrite.py`
- `app/tests/test_llm_rewrite_product_path.py`

Coverage includes:

- default disabled behavior;
- mock LLM rewrite adding a missing known area;
- InputGate routing to `area_food` from merged slots;
- low-confidence rewrite ignored;
- missing OpenAI key disables before network;
- product path remains non-clarification when high-confidence rewrite supplies enough context.

## Verification

Commands run from `backend/`:

```bash
uv run pytest app/tests/test_llm_query_rewrite.py app/tests/test_llm_rewrite_product_path.py -q -rx
uv run pytest app/tests/test_input_gate_slot_extraction.py app/tests/test_clarification_not_help_card.py app/tests/test_area_food_hot_dry_noodle.py app/tests/test_product_path_trace_persistence.py app/tests/test_shadow_benchmark_runner.py -q -rx
uv run pytest app/tests/test_amap_integration.py app/tests/test_contextual_session_history.py app/tests/test_no_smoke_for_eval.py app/tests/test_onsite_report_regressions.py app/tests/test_tavily_reference_images.py app/tests/test_admin_console.py::test_admin_prompt_versions_replay_and_rollback -q -rx
uv run pytest -q -rx
uv run alembic heads
uv run alembic current
uv run ruff check app tests
```

Result:

- Targeted LLM rewrite tests passed.
- Product routing/evidence regression cluster passed.
- Full pytest passed.
- Alembic heads/current passed.
- Ruff passed.

## Remaining Notes

- Real OpenAI query rewrite should be tested first with a small `LLM_REWRITE_ENABLED=true` batch and trace review.
- This layer is still only a candidate slot extraction aid; Iteration 5 should not let LLM rewrite directly override route decisions without an eval gate.
- Admin trace can now compare deterministic rewrite, LLM rewrite candidate, and selected rewrite source.
