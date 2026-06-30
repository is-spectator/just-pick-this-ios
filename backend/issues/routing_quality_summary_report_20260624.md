# ISS-006 Routing Quality Summary

## Scope

This slice adds a stable eval/admin summary for routing regressions. It does not change the product router, iOS UI, deterministic recommendation strategy, or benchmark definitions.

## What Changed

- Added `routing_quality_summary(...)` in `app.services.eval_review_service`.
- Added `GET /admin/api/eval-runs/{run_id}/routing-summary`.
- Added tests for:
  - `location_state_mismatch`,
  - `target_type_mismatch`,
  - venue-ordering priority regressions,
  - Haidilao area override leaks.

## Metrics

The summary reads `case_quality_scores.jsonl` and reports:

- `average_routing_score`
- `routing_issue_case_count`
- `location_state_mismatch_count`
- `target_type_mismatch_count`
- `venue_ordering_priority_issue_count`
- `wrong_location_priority_count`
- `issue_counts`
- `by_category`
- `top_cases`

## Contract

Routing should preserve:

- venue + ordering before area routing,
- stable `location_state`,
- stable `target_type`,
- no area restaurant override for in-venue ordering requests.

## Non-goals

- No product routing changes.
- No recommendation strategy changes.
- No benchmark case changes.
