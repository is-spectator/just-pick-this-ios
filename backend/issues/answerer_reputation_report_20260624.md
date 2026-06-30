# ISS-023 Answerer Quality Reputation Slice

## Scope

This slice adds a first read-only answerer quality surface for the existing help-card workflow. It does not add migrations, change reward settlement, alter finalizer ranking, or change the iOS client.

## What Changed

- Added `app.services.answerer_quality`.
- Added `GET /v1/answerers/me/quality`.
- Aggregates existing persisted signals from:
  - `help_answers`
  - `reward_events`
  - `content_review_tasks`
  - `user_behavior_events`
- Added a deterministic `quality.score` and `quality.tier`.
- Added tests for pure score behavior and the real help-card finalizer path.

## API Shape

`GET /v1/answerers/me/quality?device_id=...`

Returns:

- `user`
- `quality.score`
- `quality.tier`
- `quality.signals`
- `answers.status_counts`
- `rewards.granted_count`
- `rewards.rejected_count`
- `moderation.one_liner_rejected_count`
- `behavior.event_counts`

## Current Limitations

- It only summarizes existing persisted signals.
- It does not yet do semantic duplicate detection.
- It does not yet feed answerer reputation into finalizer evidence selection.
- It does not create a moderation queue beyond existing one-liner review tasks.

## Next Steps

1. Add semantic duplicate detection beyond exact normalized text.
2. Feed answerer quality into finalizer evidence selection as a soft tie-breaker.
3. Add ops review filters for `quality.tier=at_risk`.
4. Track answer adoption after final recommendation acceptance.

