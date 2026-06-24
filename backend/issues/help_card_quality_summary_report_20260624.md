# ISS-004 HelpCard Quality Summary

## Scope

This slice adds a stable, file-backed review surface for HelpCard quality regressions. It does not change the product runtime, iOS UI, routing policy, or deterministic recommendation behavior.

## What Changed

- Added `help_card_quality_summary(...)` in `app.services.eval_review_service`.
- Added `GET /admin/api/eval-runs/{run_id}/help-card-quality-summary`.
- Added tests for:
  - generic HelpCard title counts,
  - thin/missing context counts,
  - generic wants counts,
  - product-rule avoids counts,
  - Admin API exposure.

## Metrics

The summary reads `case_quality_scores.jsonl` and reports:

- `average_help_card_quality_score`
- `help_card_issue_case_count`
- `generic_title_count`
- `thin_context_count`
- `generic_wants_count`
- `product_rule_avoids_count`
- `issue_counts`
- `top_cases`

## Contract

HelpCards are expected to have:

- a specific title,
- structured context,
- concrete wants,
- concrete avoids,
- useful constraints.

The summary is designed to catch regressions such as:

- `北京这顿饭，求一个`
- `好吃`
- `别让我查`
- `多个选项`
- missing or overly thin context.

## Non-goals

- No new product features.
- No iOS changes.
- No benchmark case changes.
- No routing or recommendation strategy changes.
