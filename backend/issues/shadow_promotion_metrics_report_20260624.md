# Shadow Promotion Metrics Report - 2026-06-24

## Scope

ISS-021 requires shadow output to become a reviewable improvement mine without allowing it to affect product answers. This change keeps shadow audit-only and adds explicit promotion metrics to the reporting layer.

## Added

- `shadow_improvement_candidates` in `shadow_comparison_report.json`.
- `shadow_improvement_candidates`, `unsafe_shadow_count`, `review_required_count`, `autopromote_count`, `candidate_type_counts`, `priority_counts`, and `suggested_action_counts` in `shadow_promotion_candidates.json`.
- Markdown summary rows for promotion candidate reports.
- Regression tests that assert shadow candidates remain human-review-only.

## Safety Contract

- `autopromote=false` for every candidate.
- `review_required=true` for every candidate.
- Unsafe shadow outputs are counted as `unsafe_shadow_review` and remain blocked.
- Runtime schema/provider/timeout errors are routed to `shadow_runtime_reliability`, not product promotion.

## Candidate Actions

The current suggested actions map shadow diffs to review queues:

- `review_seed_gap`
- `review_evidence_policy`
- `review_clarification_or_seed_coverage`
- `fix_shadow_schema_prompt`
- `inspect_provider_reliability`
- `keep_shadow_blocked`

No seed, prompt, evaluator, or product runtime writes are performed automatically.
