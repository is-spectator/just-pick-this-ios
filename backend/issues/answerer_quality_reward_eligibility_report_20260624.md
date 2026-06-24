# Answerer Quality Reward Eligibility Report - 2026-06-24

## Scope

ISS-023 requires obvious low-quality, duplicate, or spam one-liners to stay out of the reward loop, and asks for `spam_answer_rate` plus `granted_rate` visibility.

## Existing Runtime Guards

- `assess_one_liner_quality` rejects generic/low-entropy/water answers before `HelpAnswer` creation.
- `detect_one_liner_abuse` rejects contact spam and unsafe content before reward handling.
- Cross-user duplicate one-liners are rejected by normalized key.
- Same answerer cannot answer the same help card twice.

## Added

- `answerer_quality_summary` now exposes:
  - `reward_pending_count`
  - `reward_eligible_answer_count`
  - `reward_eligibility.eligible_rate`
  - `reward_eligibility.pending_rate`
  - existing `granted_rate`
  - existing `spam_answer_rate`
- API regression tests now assert:
  - low-quality answers create no `HelpAnswer`;
  - low-quality answers create no `RewardEvent`;
  - duplicate answers do not create an extra `RewardEvent`.

## Operational Meaning

- `spam_answer_rate = (reward_rejected + one_liner_rejected_review_tasks) / submitted_count`
- `granted_rate = reward_granted / submitted_count`
- `reward_eligibility_rate = (reward_pending + reward_granted + reward_rejected) / submitted_count`

These metrics make it possible to distinguish accepted-but-pending human evidence from rejected/spam answers.
