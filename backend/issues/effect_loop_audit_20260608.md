# Effect Loop Audit 20260608

## Current State

- Product benchmark exists as `scripts/run_product_benchmark.py` and calls `/v1/chat/turn` through FastAPI ASGI with `ALLOW_EVAL_BYPASS=false`.
- Existing reports include `quality_report.*`, `case_quality_scores.jsonl`, `low_quality_cases.md`, `seed_gap_report.md`, `pipi_agent_improvement_report.md`, generated markdown issues, coverage, and shadow comparison.
- Existing scoring can identify response kind, routing, tool, persistence, card contract, evidence, and help-card specificity issues.
- Admin trace exists, but there was no eval-run review API for low-quality cases.

## Gaps Found

1. Product benchmark rows did not carry a stable `run_id`, normalized `actual`, or compact `trace` object.
2. Quality reports did not expose a single `primary_cause` suitable for downstream automation.
3. Seed gaps existed only as markdown and were not converted to structured seed candidates.
4. Agent improvement output existed as markdown, but not as structured grouped fix issues.
5. Low-quality case review had no admin API or audit path.

## Files to Fix

- `scripts/run_product_benchmark.py`
- `backend/app/eval/benchmark_cases.py`
- `backend/app/eval/product_benchmark_runner.py`
- `backend/app/eval/quality_attribution.py`
- `backend/app/eval/seed_candidate_generator.py`
- `backend/app/eval/agent_issue_generator.py`
- `backend/app/eval/reporting.py`
- `backend/app/services/eval_review_service.py`
- `backend/app/admin/routes.py`
- `scripts/run_effect_benchmark.sh`

## Risk

Medium. The work is report and review-plane heavy, but it touches benchmark output shape and admin routes. Backward compatibility is kept by preserving existing `response`, `actual_summary`, and `results.jsonl` fields.
