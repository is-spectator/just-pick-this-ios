# Finalizer Quality Follow-up 2026-06-23

## Issue

ISS-020 Finalizer Quality: `PipiFinalizeGraph` could finalize a help card when the
total answer count reached `min_answers_required`, even if useful unique human
evidence was below the threshold. This made historical imports or non-API writes
able to convert duplicate/generic "来一句" answers into a final recommendation.

## Fix

- `PipiFinalizeGraph.decide_final_answer` now requires at least
  `min_answers_required` useful unique human evidence answers.
- Generic answers such as `随便` / `都行` remain excluded.
- Duplicate answers are excluded by normalized answer fingerprint, including
  punctuation, whitespace, and numeric suffix differences.
- If useful unique evidence is insufficient, the graph returns
  `status=needs_more_answers` and does not call finalize/card/intent/light tools.
- Finalized metadata now records:
  - `human_answer_count`
  - `unique_human_evidence_count`
  - `excluded_answer_ids`
  - `excluded_answer_reasons`

## Compatibility

- The one-liner API already rejects exact duplicate normalized answers. This
  change adds a defensive graph-level guard for direct DB writes, migrations, and
  future import pipelines.
- Existing reward behavior still uses selected evidence answer IDs. Non-selected
  generic or duplicate answers stay rejectable rather than receiving finalization
  credit.
- Test fixture answers that only differed by trailing numbers were changed to
  semantically distinct useful evidence.

## Verification

Executed locally:

```bash
cd backend
uv run --extra dev pytest app/tests/test_finalize_harness_path.py app/tests/test_one_liner_quality.py -q -rx
uv run --extra dev ruff check app/agent/pipi_finalize_graph.py app/tests/test_finalize_harness_path.py app/tests/test_help_deck_api.py app/tests/conftest.py
uv run --extra dev pytest app/tests -q -rx
uv run --extra dev ruff check app tests ../scripts/run_product_benchmark.py
uv run alembic heads
```

All commands above passed. `uv run alembic current` was also attempted and failed
locally because the developer machine's PostgreSQL requires a password:
`fe_sendauth: no password supplied`.
