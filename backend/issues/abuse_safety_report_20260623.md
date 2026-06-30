# Abuse Safety Review Queue Slice

## Scope

This slice closes the first abuse-safety gap for human one-liner answers:
rejected answers are no longer discarded as opaque `422` responses. Obvious
off-platform contact spam, unsafe adult-harassment text, and low-quality
one-liners now create `content_review_tasks` for operator review.

## Runtime Behavior

- Accepted one-liners keep the existing flow:
  - create `HelpAnswer`
  - create pending `RewardEvent`
  - record user behavior
  - advance answer count/finalization
- Rejected one-liners do not create `HelpAnswer` or `RewardEvent`.
- Rejected one-liners create a `ContentReviewTask` with:
  - `task_type=one_liner_rejected`
  - `target_table=help_cards`
  - `target_record_id=<help_card_id>`
  - raw text, rejection reason, issues, and metadata in `payload_json`

## Detection Policy

The V0 detector is deliberately conservative. It only flags:

- contact/off-platform solicitation such as `加我`, `微信号`, `vx123`, `QQ`, links, or QR-code language
- explicit adult-harassment terms
- existing low-value answer classes such as generic answers, repeated
  characters, numeric-only text, and low entropy text

It does not call external moderation services and does not modify product card
or help-card routing.

## Tests

- `test_one_liner_abuse_detects_contact_spam_without_blocking_normal_advice`
- `test_rejected_one_liner_creates_content_review_task`

## Follow-ups

- Add answerer reputation and review outcomes to help-feed ranking.
- Add rate-limit events once device/account risk scoring exists.
- Add operator resolution actions for `content_review_tasks` beyond the
  existing admin list endpoint.
