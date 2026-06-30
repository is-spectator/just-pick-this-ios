# ISS-002 Low Quality Review Queue Summary Report 2026-06-24

## Scope

This closes the explicit queue-health gap for **ISS-002: 低质量 case 自动归因与人审队列**.

Existing code already generated low-quality cases, attribution rows, trace replay links, human review JSONL, review alignment, and seed draft workflows. This slice adds a queue-level summary so ops can inspect review progress without manually filtering case lists.

## Added

- `app.services.eval_review_service.low_quality_queue_summary`
- Admin endpoint `GET /admin/api/eval-runs/{run_id}/low-quality-summary`
- No-DB service test for cause distribution, review progress, and trace coverage
- Admin API assertion that the summary is exposed next to low-quality case details

## Metrics

The summary exposes:

- `low_quality_count`
- `reviewed_count`
- `pending_review_count`
- `processing_rate`
- `trace_available_count`
- `trace_coverage_rate`
- `by_primary_cause`
- `by_review_action`
- `top_cases`

## Product Meaning

The low-quality review queue now answers:

1. How many low-quality cases need human review?
2. Which causes dominate: agent bug, seed gap, card quality, or other buckets?
3. How many cases have been reviewed?
4. Can each case jump to replayable trace/admin session context?

## Non-goals

- No evaluator scoring logic changed.
- No product routing changed.
- No seed auto-approval was added.
- No iOS changes were made.
