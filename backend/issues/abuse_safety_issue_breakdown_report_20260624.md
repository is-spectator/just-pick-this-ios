# Abuse Safety Issue Breakdown Report - 2026-06-24

## Scope

ISS-024 requires unsafe content to stay out of the public feed and leave an audit trail. The runtime already blocks unsafe help-card publish and unsafe one-liners by creating `ContentReviewTask` records. This change improves observability for what kind of abuse is being flagged.

## Added

- `abuse_safety_summary.issue_counts`
- `abuse_safety_summary.source_counts`
- Regression coverage for privacy-harm help-card text such as opening/doxxing requests.

## Existing Guards

- Unsafe help cards are blocked before `published` feed exposure.
- Unsafe one-liners do not create `HelpAnswer`.
- Unsafe one-liners do not create `RewardEvent`.
- Review tasks include reason, issues, source, and priority.

## Metrics

- `flag_rate`
- `unsafe_publish_rate`
- `one_liner_rejection_share`
- issue breakdown by `payload_json.issues`
- source breakdown by `payload_json.source`

## Runtime Impact

No ranking, recommendation, iOS, or agent behavior changed. This is a safety observability and regression-test update.
