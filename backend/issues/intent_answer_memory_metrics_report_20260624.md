# ISS-013 IntentAnswer Memory Metrics

## Scope

This slice adds operational visibility for IntentAnswer memory. It does not change product retrieval, finalizer behavior, iOS UI, seed data, or the activation workflow.

## What Changed

- Added `app.services.intent_answer_metrics.intent_answer_memory_summary`.
- Added `GET /admin/api/intent-answers/memory-summary`.
- Added no-DB unit coverage for:
  - active vs draft memory count,
  - source type mix,
  - card-to-IntentAnswer hit rate,
  - referenced answer coverage,
  - success/rejection feedback totals,
  - accepted intent rate,
  - average confidence,
  - top memory rows.

## Metrics

The summary reports:

- `total_intent_answer_count`
- `active_intent_answer_count`
- `draft_intent_answer_count`
- `source_type_counts`
- `recommendation_card_count`
- `intent_answer_reference_count`
- `referenced_intent_answer_count`
- `intent_answer_hit_rate`
- `referenced_answer_coverage_rate`
- `success_count`
- `rejection_count`
- `accepted_intent_rate`
- `last_used_count`
- `average_confidence`
- `top_answers`

## Contract

IntentAnswer memory should be measurable before it is optimized:

- active rows are the product retrievable memory,
- draft rows are safe ops/import candidates,
- recommendation cards should explicitly reference memory when memory is used,
- accept/reject/post-review events should update success and rejection counters.

## Non-goals

- No automatic promotion of draft memory.
- No new seed content.
- No retrieval ranking change.
