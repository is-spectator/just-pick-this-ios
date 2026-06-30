# Seed Candidate Publish Workflow Report - 2026-06-24

## Scope

This slice finishes the backend ops workflow for ISS-029.

Existing backend support already covered:

- seed candidate generation from benchmark reports;
- human review with `seed_patch`;
- creating idempotent inactive `IntentAnswer` drafts from accepted seed patches;
- seed workflow processing-time metrics.

The missing backend gap was an explicit publish/rollback path for ops-managed `IntentAnswer` drafts.

## Changes

- Added admin publish endpoint:

```text
POST /admin/api/intent-answers/{answer_id}/publish
```

- Added admin rollback endpoint:

```text
POST /admin/api/intent-answers/{answer_id}/rollback
```

- Publish:
  - only applies to ops/import managed IntentAnswer drafts;
  - sets `is_active=true`;
  - marks evidence as `approved=true`, `draft=false`;
  - writes `publish_seed_intent_answer` audit log.

- Rollback:
  - sets `is_active=false`;
  - marks evidence as `rolled_back=true`, `approved=false`;
  - writes `rollback_seed_intent_answer` audit log.

- Seed workflow summary now includes:
  - `intent_answer_publish_count`
  - `intent_answer_publish_rate`
  - `intent_answer_rollback_count`
  - per-candidate `intent_answer_published`
  - per-candidate `intent_answer_rolled_back`

## Product Safety

- Drafts remain inactive until explicit publish.
- Rollback deactivates rather than deletes, preserving audit history.
- No product recommendation strategy changed.
- No iOS changes were made.

## Validation

Focused coverage:

```bash
uv run --extra dev pytest app/tests/test_admin_eval_review_api.py app/tests/test_seed_workflow_summary.py -q -rx
```

