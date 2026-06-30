# Seed Candidate Generator Hardening Report - 2026-06-24

## Issue

ISS-005: Seed Candidate Generator should turn benchmark `seed_gap` rows into
operator-reviewable seed drafts instead of leaving gaps as loose report text.

## Scope

This slice does not change product routing, iOS, recommendation strategy, or
active seed data. It only strengthens the eval/reporting artifact that bridges
`seed_gap` attribution to the existing admin seed draft workflow.

## Changes

- `generate_seed_candidates(...)` now emits a review-only `seed_patch` payload
  for every seed gap cluster.
- The `seed_patch` is compatible with the existing
  `POST /admin/api/eval-runs/{run_id}/cases/{case_id}/seed-intent-answer-draft`
  workflow:
  - `intent_key`
  - `intent_text`
  - `answer_type`
  - `answer_title`
  - `answer_summary`
  - `constraints`
  - top-level slot fields such as `area`, `venue`, `food_item`, `cuisine`
  - `target_type`
  - `location_state`
  - single `decision_factor`
  - `source_case_ids`
- Added `autopromote=false` and `review_status=needs_ops_review` to make it
  explicit that candidates never activate product answers without human review.
- Added `dedupe_key` and optional `existing_intent_keys` filtering so reports
  can suppress candidates that already have an approved seed.
- Kept `suggested_seed` as a backward-compatible alias for older report/admin
  consumers.

## Safety

- No candidate is activated automatically.
- No `IntentAnswer` row is written by the generator.
- Existing admin review and seed draft endpoints remain the only write path.

## Verification

Updated `app/tests/test_effect_loop_reports.py` to assert:

- seed candidates include review-only metadata;
- generated `seed_patch` preserves area/food slots;
- generated `seed_patch` has exactly one decision factor;
- generated `seed_patch` is compatible with ops draft fields;
- existing intent keys can suppress duplicate candidates.
