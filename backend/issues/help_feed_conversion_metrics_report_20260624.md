# Help Feed Conversion Metrics Report - 2026-06-24

## Scope

This slice hardens **ISS-022 Help Feed Ranking** from the issue workbook.

Previous work already ranked the help feed by reward, answer scarcity, answer count, and answerer preference match. The remaining gap was observability: we could not prove whether preference-matched feed placement improved the downstream `one_liner_submitted` conversion target.

## Changes

- Added `help_feed_conversion_summary(...)` in `app.services.help_feed`.
- Added pure helper `help_feed_conversion_summary_from_events(...)` for no-DB verification.
- Added admin endpoint:
  - `GET /admin/api/help-feed/conversion-summary`
- The endpoint compares:
  - `matched`: help feed impressions where `feed_ranking.preference_match.score > 0`
  - `baseline`: help feed impressions without a preference match
- It reports:
  - matched and baseline impression pairs
  - matched and baseline submitted pairs
  - matched and baseline one-liner submit rates
  - `one_liner_submit_rate_uplift`
  - `target_met` against a default `+20%` uplift target

## Why This Matters

ISS-022 asked for ranking quality, not just deterministic sort behavior. The new summary lets ops verify whether personalized help feed ranking actually moves the desired product metric: users submitting useful one-liners after seeing cards in the feed.

## Validation

Added tests in `backend/app/tests/test_help_feed_ranking.py`:

- `test_help_feed_conversion_summary_measures_preference_match_uplift`
- `test_help_feed_conversion_summary_handles_missing_baseline`

These tests run without a database and verify the uplift calculation directly from behavior events.

## Notes

- This does not change feed ranking behavior.
- This does not change reward logic.
- This does not require a migration; it uses existing `UserBehaviorEvent` rows.
- The metric depends on `help_feed_impression` payloads retaining `feed_ranking.preference_match.score`, which is already written by the feed endpoint.
