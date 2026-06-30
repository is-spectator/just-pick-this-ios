# Shadow Promotion Candidate Report - 2026-06-23

## Scope

Implemented ISS-021 as a reporting-only slice. Shadow LLM decisions remain audit-only and cannot affect product answers, tool calls, recommendation cards, or help cards.

## Changes

- Added `app.eval.shadow_promotion_generator` to convert shadow comparison decisions into review candidates.
- Integrated shadow promotion reports into `write_quality_reports`.
- Added JSONL, JSON, and Markdown outputs:
  - `shadow_promotion_candidates.jsonl`
  - `shadow_promotion_candidates.json`
  - `shadow_promotion_candidates.md`
- Added tests for report generation and candidate classification.

## Behavior

- Candidates are generated only for mismatches, unsafe shadow decisions, or shadow runtime/schema failures.
- Every candidate has `autopromote=false` and `review_required=true`.
- Shadow runtime failures are classified as `shadow_runtime_reliability`.
- Positive quality deltas are marked as `possible_improvement`, but still require human review.
- Unsafe shadow outputs are blocked as `unsafe_shadow_review`.

## Verification

- `uv run --extra dev pytest app/tests/test_quality_report_generation.py app/tests/test_shadow_promotion_candidates.py -q -rx` passed.
- `uv run --extra dev pytest app/tests -q -rx` passed with local DB-backed integration tests skipped by the existing no-DB policy.
- `uv run --extra dev ruff check app tests` passed.
- `uv run alembic heads` printed `0013_user_behavior_events (head)`.
- `uv run alembic current` could not complete locally because Postgres on `127.0.0.1:5432` requires credentials; no migration files were changed in this slice.

## Remaining Work

- Use real benchmark shadow output to calibrate prioritization thresholds.
- Add an ops workflow for human review and explicit promotion decisions.
- Keep promotion writeback out of product path until a reviewed migration path exists.
