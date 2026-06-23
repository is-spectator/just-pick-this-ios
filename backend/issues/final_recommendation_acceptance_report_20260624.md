# Final Recommendation Acceptance Report - 2026-06-24

## Issue

ISS-008: 用户行为埋点需要覆盖“就这个、换一个、问真人、发出去、来一句、采纳”。此前普通推荐卡已有 `accept`，求助卡有 `publish`，答主有 `one-liner`，但求助最终答案的“采纳”只有事件类型常量，没有专用产品 API。

## Scope

This slice only adds the backend signal path for accepting a finalized help-card recommendation. It does not change iOS, PipiLoop, finalizer ranking, reward settlement, or recommendation strategy.

## Changes

- Added `POST /v1/help-cards/{help_card_id}/accept-final`.
- The route requires the help card to have a `final_recommendation_card`.
- The final recommendation card is marked `accepted`.
- A bound `UserBehaviorEvent` is written:
  - `event_type=final_recommendation_accepted`
  - `help_card_id=<help_card_id>`
  - `recommendation_card_id=<final_card_id>`
  - `conversation_id=<help_card.conversation_id>`
- The event uses the existing user behavior pipeline, so IntentAnswer memory and user preference memory can consume it.

## Safety

- If the help card is not final-ready, the route returns `409 final_recommendation_not_ready`.
- No final card is synthesized by this endpoint.
- No reward status is changed by this endpoint.

## Verification

Added `test_accept_final_recommendation_writes_behavior_event` to cover:

- finalizer produces a final recommendation card;
- accepting final recommendation returns `final_recommendation_accepted`;
- the event is bound to both help card and recommendation card;
- the final card status becomes `accepted`;
- the event is recognized as a core behavior event.

