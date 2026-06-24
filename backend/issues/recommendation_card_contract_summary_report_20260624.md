# ISS-003 Recommendation Card Contract Summary Report 2026-06-24

## Scope

This closes the explicit metrics gap for **ISS-003: 推荐卡内容硬闸：一个选择 + 一个决策因子**.

Existing runtime guardrails already reject legacy display fields and force v2 card responses through `item + decision_factor + image optional`. This slice adds a run-level card contract summary for eval/admin review.

## Existing Guardrails

- `create_recommendation_card` rejects `reasons`, `bullets`, `followups`, and `warning`.
- `CardSummary` / `CardDetail` strip legacy fields from default API responses.
- `Evaluator` rejects multiple decision factors and missing evidence.
- `AnswerGate` blocks card JSON that did not come from a tool result.

## Added

- `app.services.eval_review_service.card_contract_summary`
- Admin endpoint `GET /admin/api/eval-runs/{run_id}/card-contract-summary`
- No-DB tests for:
  - too many decision factors
  - legacy field violations
  - average card contract score

## Metrics

The summary exposes:

- `average_card_contract_score`
- `card_contract_issue_case_count`
- `too_many_decision_factor_count`
- `legacy_field_violation_count`
- `issue_counts`
- `top_cases`

## Contract

Default recommendation card responses must remain:

- one `item`
- one `decision_factor`
- optional `image`
- no `reasons`
- no `bullets`
- no `followups`
- no `warning`

## Non-goals

- No DB field migration was added.
- No iOS changes were made.
- No recommendation strategy changed.
