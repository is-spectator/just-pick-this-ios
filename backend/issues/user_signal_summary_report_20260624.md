# User Signal Summary Report - 2026-06-24

## Scope

This slice hardens **ISS-008 User Signals**.

The backend already recorded the core behavior events for recommendation cards, help cards, feed impressions, one-liners, rewards, and final recommendation acceptance. The remaining gap was metric accessibility: ops needed a direct summary for the north-star adjacent rates instead of hand-querying raw `UserBehaviorEvent` rows.

## Changes

- Added `app.services.user_signal_metrics`.
- Added pure helper `user_signal_summary_from_records(...)` for no-DB validation.
- Added DB wrapper `user_signal_summary(...)`.
- Added admin endpoint:
  - `GET /admin/api/user-signals/summary`

## Metrics

The summary reports:

- `accepted_card_rate`
- `followup_rate`
- `help_publish_rate`
- `one_liner_submit_rate`
- recommendation card shown/accepted/follow-up counts
- help card draft/published counts
- help feed impression and one-liner submitted pairs
- per-core-event coverage booleans

## Event Coverage

The summary tracks the core event family:

- `recommendation_card_accepted`
- `recommendation_card_rejected`
- `recommendation_card_changed`
- `ask_human_requested`
- `help_card_published`
- `help_feed_impression`
- `one_liner_submitted`
- `one_liner_reward_granted`
- `one_liner_reward_rejected`
- `final_recommendation_accepted`

## Validation

Added no-DB tests in `backend/app/tests/test_user_signal_metrics.py`:

- `test_user_signal_summary_tracks_north_star_rates`
- `test_user_signal_summary_handles_empty_denominators`

These tests verify accepted/follow-up/help-publish/one-liner submit rates directly from synthetic behavior records.

## Notes

- This does not change event ingestion.
- This does not change recommendation or help-card behavior.
- This does not require a migration; it reads existing card/help-card rows and `UserBehaviorEvent` rows.
