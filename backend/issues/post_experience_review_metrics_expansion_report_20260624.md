# Post-experience Review Metrics Expansion - 2026-06-24

## Scope

This slice finishes the backend-only part of ISS-028 without touching iOS.

The backend already had:

- `POST /v1/cards/{card_id}/review`
- post-review outcomes:
  - `went_satisfied`
  - `went_regretted`
  - `not_went`
  - `unknown`
- `GET /admin/api/post-experience/summary`
- `post_review_rate`, `regret_rate`, and `not_went_rate`

## Change

The admin summary now also includes:

- `satisfaction_rate = went_satisfied / (went_satisfied + went_regretted)`
- `reviewed_after_acceptance_rate = reviews for accepted cards / post_review_count`

These make the issue sheet's “actual result / regret / satisfied” loop easier to inspect without hand-querying raw user behavior events.

## Product Safety

- No mobile UI changed.
- No event names changed.
- Existing review API responses remain compatible.
- Existing IntentAnswer feedback updates remain unchanged.

## Validation

Focused test:

```bash
uv run --extra dev pytest app/tests/test_post_experience_review_summary.py -q -rx
```

