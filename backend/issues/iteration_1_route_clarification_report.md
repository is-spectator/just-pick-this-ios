# Iteration 1 Route And Clarification Report

## Conclusion

Iteration 1 is implemented and verified.

The first-pass route gate now records deterministic query rewrite slots, separates clarification from help-card drafting, and preserves product retrieval behavior for existing AMap and benchmark paths.

## Implemented

- Added deterministic query rewrite in `app/services/query_rewrite.py`.
- Extended `InputGateResult` with missing slots, location state, decision domain, canonical query, extracted slots, and route priority.
- Updated `run_input_gate` so chitchat, clarification, venue ordering, area food, publish, and update paths are explicit.
- Kept InputGate slot extraction in trace/debug without replacing the product retrieval rewrite.
- Ensured venue ordering outranks area routing for cases like `三里屯海底捞`.
- Kept vague food/order requests as clarification instead of help cards.
- Preserved contextual short follow-ups by folding previous turn context into help-card prompt when needed.
- Restored regression behavior for AMap, travel/product deterministic routes, Top 10 single-card routing, and one-liner threshold cases.

## Verification

```bash
cd backend
uv run pytest -q -rx
uv run alembic heads
uv run alembic current
uv run ruff check app tests
```

Results:

- `pytest`: passed
- `alembic heads`: `0007_agent_prompt_configs (head)`
- `alembic current`: `0007_agent_prompt_configs (head)`
- `ruff`: passed

## Notes

- Query rewrite remains deterministic and does not call LLM.
- Product path remains PipiLoop-based.
- Eval/smoke bypass remains guarded.
- Non-debug responses do not expose extra route/debug fields.
