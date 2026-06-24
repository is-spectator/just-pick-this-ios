# ISS-011 Ops Review Workflow Summary

## Scope

This slice strengthens the low-quality case human-review workflow. It does not change product runtime behavior, deterministic routing, recommendation strategy, iOS UI, or benchmark case definitions.

## What Changed

- Added `review_workflow_summary(...)` in `app.services.eval_review_service`.
- Added `GET /admin/api/eval-runs/{run_id}/review-workflow-summary`.
- Added tests for:
  - low-quality review processing rate,
  - suggested fix counts,
  - seed patch counts,
  - accepted seed gap counts,
  - review action and label distributions,
  - Admin API exposure.

## Existing Workflow Confirmed

The existing review endpoint already supports:

- `action`
- `notes`
- `labels`
- `suggested_fix`
- `seed_patch`
- audit log persistence
- follow-up seed intent answer draft creation.

## Metrics

The summary reads `quality_attribution.jsonl`, `case_quality_scores.jsonl`, and `human_reviews.jsonl`, then reports:

- `total_review_events`
- `reviewed_case_count`
- `low_quality_count`
- `reviewed_low_quality_count`
- `pending_low_quality_count`
- `low_quality_processing_rate`
- `suggested_fix_count`
- `seed_patch_count`
- `accepted_seed_gap_count`
- `agent_bug_count`
- `needs_more_data_count`
- `by_review_action`
- `by_label`

## Contract

Low-quality review should make the eval loop operable:

- every low-quality case can be marked as seed gap, agent bug, not issue, or needs more data,
- human review can carry a concrete suggested fix,
- accepted seed gaps can carry a structured seed patch,
- ops can see throughput and pending work.

## Non-goals

- No product runtime changes.
- No UI changes.
- No automatic seed publishing.
