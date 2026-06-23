# Effect Loop Final Report 20260608

## Scope

Implemented the effect-loop landing slice for product benchmark results, quality attribution, seed candidates, agent fix issues, admin review APIs, and script-level report generation. This round did not change iOS, deterministic product routing strategy, or LLM behavior.

## What Changed

- Added importable benchmark helpers:
  - `app.eval.benchmark_cases`
  - `app.eval.product_benchmark_runner`
- Extended product benchmark rows with:
  - `run_id`
  - normalized `actual`
  - compact `trace`
  - `status`
  - `retrieval_run_id`
  - runtime-bypass issue tagging
- Added quality attribution:
  - `quality_attribution.json`
  - `quality_attribution.jsonl`
  - `primary_cause` classification
- Added structured follow-up outputs:
  - `seed_candidates.jsonl`
  - `seed_candidates.json`
  - `seed_candidates.md`
  - `agent_fix_issues.json`
  - `agent_fix_issues.jsonl`
  - `agent_fix_issues.md`
- Added Admin review endpoints:
  - `GET /admin/api/eval-runs`
  - `GET /admin/api/eval-runs/{run_id}/low-quality-cases`
  - `GET /admin/api/eval-runs/{run_id}/cases/{case_id}`
  - `POST /admin/api/eval-runs/{run_id}/cases/{case_id}/review`
- Added `scripts/run_effect_benchmark.sh`.

## Verification

- `cd backend && uv run pytest -q -rx`: passed.
- `cd backend && uv run ruff check app tests`: passed.
- `cd backend && uv run alembic heads && uv run alembic current`: passed.
- `OUT=/tmp/pipi-effect-check LIMIT=3 ./scripts/run_effect_benchmark.sh`: passed.

## Product Path Guard

The product benchmark runner continues to call `/v1/chat/turn` through FastAPI ASGI with:

- `PIPI_EVAL_MODE=false`
- `ALLOW_EVAL_BYPASS=false`
- `AUTO_SEED_ON_REQUEST=false`
- `PIPI_MODEL_PROVIDER=deterministic`
- `LLM_SHADOW_ENABLED=false`
- `LLM_REWRITE_ENABLED=false`
- `WEB_SEARCH_PROVIDER=disabled`

Rows whose response metadata reports anything other than `runtime_path=product` are marked with issue `runtime_bypass`.

## How Reports Drive Next Work

- `quality_attribution.jsonl` answers "why did this fail/degrade?"
- `seed_candidates.jsonl` answers "which approved answers should data ops add?"
- `agent_fix_issues.jsonl` answers "which runtime/router/card/retrieval fixes should engineering take?"
- Admin review endpoints let operators inspect and label low-quality cases while writing `AdminAuditLog`.

## Remaining Work

- Persist eval review decisions beyond `AdminAuditLog` if long-term dashboard filtering needs structured review state.
- Add richer slot extraction to seed candidate grouping if candidates become too coarse.
- Connect admin web UI to the new eval-run API; backend API is ready.
