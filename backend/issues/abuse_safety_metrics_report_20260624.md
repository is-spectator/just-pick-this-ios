# Abuse Safety Metrics Report 2026-06-24

## Scope

This closes the ISS-024 follow-up for observable abuse-safety metrics. It does not change moderation policy, mobile UX, help-feed ranking, or answer acceptance behavior.

## Added

- `app.services.abuse_safety_metrics.abuse_safety_summary`
- Admin endpoint `GET /admin/api/safety/abuse-summary`
- Unit tests for rate calculations and empty-denominator handling

## Metrics

The summary exposes:

- `unsafe_publish_rate`: rejected unsafe help cards divided by created help cards
- `flag_rate`: rejected help cards and one-liners divided by created help cards plus rejected one-liners
- `one_liner_rejection_share`: rejected one-liners divided by all tracked abuse review tasks
- `open_abuse_review_task_count`
- `high_priority_abuse_task_count`
- task counts for `help_card_rejected` and `one_liner_rejected`

## Data Sources

- `HelpCard`
- `ContentReviewTask`

Tracked review task types:

- `help_card_rejected`
- `one_liner_rejected`

## Admin Use

Operators can inspect recent abuse-safety health through:

```http
GET /admin/api/safety/abuse-summary?since_hours=720
```

The endpoint writes an admin audit event with action `view_abuse_safety_summary`.

## Notes

- The endpoint is read-only except for admin audit logging.
- No user-facing product behavior changed.
- The summary function is testable without a database via `abuse_safety_summary_from_records`.
