# User Preference Memory V1 Report - 2026-06-23

## Issue

ISS-015: 用户偏好记忆 V1：地域 / 口味 / 排队 / 预算 / 同行人。

## Scope

This slice adds a backend preference-memory foundation using existing product behavior events. It does not change iOS, product recommendation strategy, PipiLoop routing, or LLM behavior.

## Changes

- Added `app.services.user_preferences`.
- Updates `users.profile_json["preference_memory_v1"]` from explicit behavior event metadata and recommendation card accept/reject events.
- Tracks counters and summaries for:
  - cuisines
  - food items
  - taste preferences
  - spice preferences
  - budget preferences
  - companions
  - areas
  - accepted items/categories/places
- Added `GET /v1/users/preferences` for reading the current preference memory by `device_uid`, `device_id`, or `user_id`.
- Integrated memory updates into `record_user_behavior_event`.

## Behavior

- Positive events such as `recommendation_card_accepted` add stronger positive weight.
- Negative events such as `recommendation_card_rejected` / `recommendation_card_changed` subtract weight.
- Explicit metadata such as `cuisine`, `taste_preference`, `spice_preference`, `budget_preference`, `companion`, and `area` is preserved in the user's memory.
- V1 stores into `User.profile_json` to avoid a migration while validating the product loop.

## Verification

- Added pure unit coverage in `app/tests/test_user_preference_memory.py`.
- Extended behavior-event integration coverage in `app/tests/test_user_behavior_events.py` for `GET /v1/users/preferences`.

## Remaining Work

- Feed `preference_memory_v1.summary` into ContextBuilder once enough real behavior data exists.
- Add explicit iOS feedback controls for budget, queue tolerance, companion, and disliked categories.
- Promote to a dedicated `user_preferences` table if the JSON profile becomes too coarse for analytics.
