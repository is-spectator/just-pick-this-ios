# ISS-014 Evidence Quality Summary

## Scope

This slice adds eval/admin visibility for evidence grounding and image safety. It does not change retrieval, Tavily usage, image selection, product ranking, or iOS UI.

## What Changed

- Added `evidence_quality_summary(...)` in `app.services.eval_review_service`.
- Added `GET /admin/api/eval-runs/{run_id}/evidence-summary`.
- Added tests for:
  - missing evidence ids,
  - unverified image assets,
  - non-displayable image assets,
  - AI-generated image assets,
  - missing image source domain,
  - category distribution and top cases.

## Metrics

The summary reads `case_quality_scores.jsonl` and reports:

- `average_evidence_grounding_score`
- `evidence_issue_case_count`
- `missing_evidence_count`
- `image_not_verified_count`
- `image_not_displayable_count`
- `ai_image_count`
- `image_missing_source_domain_count`
- `issue_counts`
- `by_category`
- `top_cases`

## Contract

Recommendation cards must have evidence ids. Images are optional, but when present they must be:

- verified,
- displayable,
- non-AI,
- source-attributed.

## Non-goals

- No new Tavily calls.
- No image verification workflow changes.
- No product retrieval ranking changes.
