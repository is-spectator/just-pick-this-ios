# ISS-009 Reward Loop Metrics Report 2026-06-24

## Scope

This slice closes the observability gap for **ISS-009: 来一句奖励闭环 V1**.

Existing product code already creates pending reward events for one-liners and settles selected evidence as `granted` while non-selected pending answers become `rejected` during finalization. This slice adds a stable summary surface for ops and regression tests.

## Added

- `app.services.reward_loop_metrics.reward_loop_summary`
- Admin endpoint `GET /admin/api/rewards/loop-summary`
- No-DB tests for reward settlement and binding rate math

## Metrics

The summary exposes:

- `pending_count`
- `granted_count`
- `rejected_count`
- `settled_count`
- `pending_value`
- `granted_value`
- `rejected_value`
- `settlement_rate`
- `grant_rate`
- `rejection_rate`
- `answer_binding_rate`
- `help_card_binding_rate`
- `answer_reward_pending_rate`

## Binding Checks

`answer_binding_rate` and `help_card_binding_rate` verify that reward ledger rows remain connected to both the submitted human evidence and the originating help card. This makes final answer settlement auditable instead of only visible through individual row inspection.

## Admin Use

```http
GET /admin/api/rewards/loop-summary?since_hours=720
```

The endpoint writes an admin audit event with action `view_reward_loop_summary`.

## Non-goals

- No cashout or payment flow was added.
- No reward amount policy changed.
- No iOS changes were made.
- No finalizer selection policy changed.
