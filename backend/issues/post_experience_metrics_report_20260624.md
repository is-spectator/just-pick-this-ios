# Post-experience Metrics Report - 2026-06-24

## Scope

This slice hardens **ISS-028 Post-experience Review**.

The existing backend already accepted post-experience feedback (`went_satisfied`, `went_regretted`, `not_went`, `unknown`) and used satisfied/regretted outcomes as `IntentAnswer` memory signals. The remaining gap was metric visibility: ops could not directly inspect `post_review_rate` or `regret_rate` without hand-querying raw behavior events.

## Changes

- Added `post_experience_review_summary(...)` in `app.services.cards`.
- Added pure helper `post_experience_review_summary_from_events(...)` for no-DB metric verification.
- Added admin endpoint:
  - `GET /admin/api/post-experience/summary`

## Metrics

The summary reports:

- `accepted_card_count`
- `post_review_count`
- `post_review_rate = post_review_count / recommendation_card_accepted`
- outcome counts:
  - `went_satisfied`
  - `went_regretted`
  - `not_went`
  - `unknown`
- `regret_rate = went_regretted / (went_satisfied + went_regretted)`
- `not_went_rate`
- `reviewed_after_acceptance_count`
- `unaccepted_review_count`

## Validation

Added no-DB tests in `backend/app/tests/test_post_experience_review_summary.py`:

- `test_post_experience_summary_tracks_review_and_regret_rates`
- `test_post_experience_summary_uses_latest_review_per_card`
- `test_post_experience_summary_accepts_payload_outcome_fallback`

These tests verify the metric math directly from synthetic behavior events and keep the safety net available when local Postgres is unavailable.

## Notes

- This does not change recommendation behavior.
- This does not change mobile UI.
- This does not require a migration; it reads existing `UserBehaviorEvent` rows.
- IntentAnswer scoring remains handled by the existing post-review event path.
