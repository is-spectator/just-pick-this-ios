# Seed Workflow Metrics Report - 2026-06-24

## Scope

This slice tightens the remaining evidence gap for:

- `ISS-016 Seed Package`: top seed candidates need a measurable processing rate.
- `ISS-029 Ops Workflow`: seed candidate -> approved/draft `IntentAnswer` workflow needs measurable processing time.

It does not change product recommendation strategy, mobile UI, or the seed candidate generator. It only adds an admin/read-only measurement surface over the existing review workflow.

## Added Runtime Surface

`GET /admin/api/eval-runs/{run_id}/seed-workflow-summary?top_limit=50`

The endpoint reads:

- file-backed `seed_candidates.jsonl` for the eval run;
- `AdminAuditLog.action=review_eval_case`;
- `AdminAuditLog.action=create_seed_intent_answer_draft`;
- `AdminAuditLog.action=import_intent_answer_drafts`.

It returns:

- `candidate_count`
- `top_candidate_count`
- `reviewed_count`
- `accepted_seed_gap_count`
- `intent_answer_draft_count`
- `processed_count`
- `processing_rate`
- `intent_answer_draft_rate`
- `target_processing_rate=0.8`
- `processing_rate_target_met`
- `average_processing_hours`
- `target_processing_hours=48`
- `processing_time_target_met`
- per-candidate review/draft/process details

## Measurement Semantics

`processed=true` if a top seed candidate has either:

- any explicit human review action for one of its source cases; or
- a draft/imported `IntentAnswer` linked by `source_ref_id={run_id}:{case_id}`.

`intent_answer_drafted=true` if an ops seed patch or import created an `IntentAnswer` draft for one of the candidate source cases.

This keeps the existing safety model intact: generated candidates remain review-only and never auto-activate product answers.

## Tests

Added:

- `backend/app/tests/test_seed_workflow_summary.py`
  - verifies unprocessed candidates are exposed;
  - verifies review + draft events produce `processing_rate=1.0`, `intent_answer_draft_rate=1.0`, and SLA-compliant average processing time without a database.

Extended:

- `backend/app/tests/test_admin_eval_review_api.py`
  - verifies the admin endpoint across unprocessed -> reviewed -> drafted states.

Updated:

- `backend/app/tests/conftest.py`
  - adds `test_seed_workflow_summary.py` to the no-DB test allowlist.

## Verification

Commands run locally:

```bash
cd backend
uv run --extra dev pytest app/tests/test_seed_workflow_summary.py -q -rx
uv run --extra dev pytest app/tests/test_seed_workflow_summary.py app/tests/test_admin_eval_review_api.py -q -rx
uv run --extra dev pytest app/tests -q -rx
uv run --extra dev ruff check app tests
uv run alembic heads
```

Results:

- `test_seed_workflow_summary.py`: passed.
- Admin DB integration tests were skipped locally because the database is not reachable; the newly added no-DB summary tests ran and passed.
- Full locally runnable test set passed under the repository's no-DB skip policy.
- Ruff passed.
- Alembic heads passed.

## Remaining Verification

Run `./scripts/test.sh` or the CI backend test job with PostgreSQL available to execute the admin integration assertions end-to-end.
