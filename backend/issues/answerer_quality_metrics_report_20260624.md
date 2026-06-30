# Answerer Quality Metrics Report - 2026-06-24

## Scope

This slice hardens **ISS-023 Answerer Quality**.

Earlier work rejected low-quality one-liners and exposed per-answerer quality scores. The remaining gap was metric visibility for the issue's key metrics: `spam_answer_rate` and `granted_rate`.

## Changes

- Added `calculate_answerer_quality_rates(...)`.
- Added `answerer_quality_summary(...)`.
- Added pure helper `answerer_quality_summary_from_counts(...)`.
- Added admin endpoint:
  - `GET /admin/api/answerers/quality-summary`
- Extended `/v1/answerers/me/quality` output with a `rates` object.

## Metrics

The summary reports:

- `submitted_count`
- `reward_granted_count`
- `reward_rejected_count`
- `review_rejection_count`
- `negative_answer_count`
- `rates.granted_rate`
- `rates.spam_answer_rate`
- `rates.reward_rejected_rate`
- `rates.review_rejection_rate`

Definitions:

- `granted_rate = reward_granted / submitted_count`
- `spam_answer_rate = (reward_rejected + one_liner_rejected_review_tasks) / submitted_count`

## Validation

Updated `backend/app/tests/test_answerer_quality.py`:

- `test_answerer_quality_rates_track_granted_and_spam_answers`
- `test_answerer_quality_summary_handles_empty_denominators`

These no-DB tests verify the rate math directly.

## Notes

- This does not change one-liner acceptance.
- This does not change reward settlement.
- This does not change finalizer evidence selection.
- It gives ops a stable summary endpoint for ISS-023 monitoring.
