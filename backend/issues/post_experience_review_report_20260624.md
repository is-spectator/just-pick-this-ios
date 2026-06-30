# Post-experience Review Report 2026-06-24

## Issue

ISS-028: 消费后复盘。此前后端有推荐卡 accept/reject/change 事件，但缺少
“去了 / 没去 / 满意 / 后悔”的专用 post-experience review 入口，长期
`IntentAnswer` 质量只能从即时点击间接推断。

## Changes

- Added `POST /v1/cards/{card_id}/review`.
- Added request schema `CardPostReviewRequest`.
- Supported outcomes:
  - `went_satisfied`
  - `went_regretted`
  - `not_went`
  - `unknown`
- The route writes `UserBehaviorEvent` records:
  - `recommendation_card_post_review_satisfied`
  - `recommendation_card_post_review_regretted`
  - `recommendation_card_post_review_not_went`
  - `recommendation_card_post_review_unknown`
- `IntentAnswer` memory now treats:
  - `went_satisfied` as a success signal;
  - `went_regretted` and `not_went` as rejection signals.

## Safety

- No iOS changes.
- No agent routing changes.
- No recommendation regeneration.
- `unknown` review is recorded as a core behavior event but does not change
  `IntentAnswer.success_count` or `rejection_count`.

## Verification

Updated `app/tests/test_p10_intent_answer_memory.py` to assert:

- satisfied post-review increments `success_count`;
- regretted post-review increments `rejection_count`;
- event types are returned by the new API.

Executed locally:

```bash
cd backend
uv run --extra dev pytest app/tests -q -rx
uv run --extra dev ruff check app tests ../scripts/run_product_benchmark.py
uv run alembic heads
```

All commands above passed.
