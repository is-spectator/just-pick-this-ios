# Ops Seed Patch Workflow Report 2026-06-23

## Issue

ISS-029 Ops Workflow: low-quality review records could store `seed_patch`, but
there was no explicit backend workflow to turn an accepted seed gap into a draft
`IntentAnswer`.

## Scope

This slice only adds an admin workflow. It does not change product routing,
PipiLoop behavior, recommendation strategy, iOS, or benchmark cases.

## Changes

- Added `app.services.seed_patch_workflow`.
- Added admin endpoint:
  - `POST /admin/api/eval-runs/{run_id}/cases/{case_id}/seed-intent-answer-draft`
- The endpoint can either:
  - use the request body's `seed_patch`; or
  - load the latest reviewed `accept_seed_gap` seed patch for the case.
- The workflow creates or updates an `IntentAnswer` draft:
  - `source_type=ops_seed_patch`
  - `source_ref_id={run_id}:{case_id}`
  - `is_active=false`
  - `evidence_json.draft=true`
  - `evidence_json.approved=false`
- The operation is idempotent for the same `run_id:case_id`.
- Admin audit logs record `create_seed_intent_answer_draft`.

## Safety

Draft seed answers are intentionally inactive, so they do not affect product
retrieval or card creation until a later explicit publish/approval workflow.

## Verification

Updated `app/tests/test_admin_eval_review_api.py` to verify:

- review can persist `seed_patch`;
- seed patch can be promoted to an inactive draft `IntentAnswer`;
- promotion is idempotent;
- missing `intent_key` is rejected with `422`;
- admin audit logs capture the promotion.
