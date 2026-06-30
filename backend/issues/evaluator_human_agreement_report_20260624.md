# ISS-018 Evaluator Human Agreement Report

## Scope

This slice adds a measurable human-review agreement loop for evaluator rules without changing routing, recommendation strategy, iOS, or database schema.

## Changes

- Admin eval case reviews are now appended to `human_reviews.jsonl` next to the benchmark report files.
- Added `review_alignment_summary(...)` for comparing evaluator attribution with latest human review action per case.
- Added `GET /admin/api/eval-runs/{run_id}/review-alignment`.
- Review action mapping:
  - `accept_seed_gap` -> `seed_gap`
  - `mark_agent_bug` -> `agent_bug`
  - `mark_not_issue` -> `not_issue`
  - `needs_more_data` remains non-comparable

## Metrics

The alignment summary reports:

- `total_reviews`
- `comparable_reviews`
- `agreements`
- `disagreements`
- `agreement_rate`
- `quality_human_agreement` (alias for evaluator/human agreement)
- `false_positive_count`
- `false_positive_rate`
- `false_negative_count`
- `false_negative_rate`
- `target_agreement_rate=0.75`
- `target_met`
- disagreement case payloads for rule tuning

False-positive definition:

```text
human review action = mark_not_issue
and evaluator predicted a problem cause such as agent_bug / seed_gap / card_quality.
```

This directly supports the ISS-018 metric requirement `false_positive_rate`.

## Verification

- Added no-DB service tests for agreement and disagreement cases.
- Added no-DB service tests for false-positive rate calculation.
- Extended admin eval review API tests to verify `human_reviews.jsonl` persistence and the alignment endpoint.

## Notes

This does not claim evaluator quality is solved. It gives ops and benchmark reporting an auditable metric for ISS-018's human-review agreement target, so future rule changes can be judged against reviewed cases instead of anecdotes.
