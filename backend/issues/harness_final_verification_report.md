# Harness Final Verification Report

Date: 2026-05-27

Scope: multi-agent QA/docs/dead-path review plus Coordinator verification. This report is based on the current
code, targeted tests, full regression tests, and static inspection. It does not assume
`backend/issues/final_report.md` is authoritative.

## Current `/v1/chat/turn` Path

Normal product path, excluding explicit eval/smoke bypasses:

1. `backend/app/api/routes_chat.py` exposes `POST /v1/chat/turn`.
2. The route calls `app.services.chat.run_chat_turn`.
3. `run_chat_turn` persists the user `Turn`.
4. `run_chat_turn` calls `InputGate`.
5. If the gate says `should_enter_loop=false`, `PipiChatGraph` returns a direct
   answer without retrieval or tool execution.
6. If the gate enters the loop, `run_chat_turn` builds the DB-backed retriever,
   context provider, and runtime tool executor.
7. `run_chat_turn` invokes `build_pipi_chat_graph()` with
   `{"configurable": {"thread_id": conversation_id}}`.
8. `PipiChatGraph` runs only these wrapper nodes:
   `persist_turn -> input_gate -> build_context -> run_pipi_loop -> persist_response`.
9. `run_pipi_loop` calls the injected service runner.
10. The service runner calls `PipiLoop.run`.
11. `PipiLoop` drives `Reasoner -> DbPipiAbilityCenter -> ToolResult -> Evaluator
    -> Reasoner -> AnswerGate`.
12. The service persists the assistant `Turn`, `AgentRun.output_json`,
    `ToolCall` rows, cards/help cards/light events, and returns top-level
    `ui_events` plus `metadata.loop`.

## PipiLoop Status

`PipiLoop` is the single-turn agent engine for tool-capable product turns.
Greeting/smalltalk/app-help/unknown turns are intentionally stopped by
`InputGate` and direct-answer before the tool loop.

Current caveat: `PipiLoop` still has `max_iters` and `answer_gate_failed` safe
exits. These do not create cards, but they mean `AnswerDecision` is the normal
successful loop exit rather than the only possible terminal branch.

## Ability Boundary Status

The product path does not use `DeferredAbilityCenter`.

The product path currently uses a DB-backed ability boundary:

- `DbPipiAbilityCenter` handles `search_knowledge`.
- `DbPipiAbilityCenter` delegates card/help/finalize tools to `DbToolExecutor`.

The generic `backend/app/ability/center.py` exists and has schema/permission
guardrails. The product path currently treats `DbPipiAbilityCenter` as the
DB-backed AbilityCenter implementation, with `DbToolExecutor` as its internal
DB runtime helper for card/help/finalize tools. The main path no longer uses
`DeferredAbilityCenter`.

## Old Path Residuals

Residual code exists but is not in the compiled chat graph main path:

- `rewrite_query`
- `retrieve_knowledge`
- `evaluate_evidence`
- `decide_next_action`
- `execute_tool`
- `respond`

These functions remain in `backend/app/agent/pipi_chat_graph.py` and are still
exported from `backend/app/agent/__init__.py` for compatibility. The compiled
graph does not add them as nodes.

`DeferredAbilityCenter` remains as a direct graph/unit-test fallback when no
DB-backed runner is injected. It is not used by the normal `/v1/chat/turn`
service path.

Legacy multi-reason fields still exist in model/serializer compatibility
surfaces, such as `bullets_json`, `followups`, and old card composer helpers.
The current evaluator/tool contract rejects `reasons`, `bullets`, and
`followups` for recommendation-card creation, but the legacy storage fields are
not fully removed.

## Trace Status

Targeted inspection and tests show the loop can now emit these first-class
events:

- `input_gate_result`
- `context_pack`
- `reasoner_decision`
- `tool_call`
- `tool_result`
- `evaluator_result`
- `answer_gate_result`

Coordinator regression passed after the trace events were added to `PipiLoop`.

## Test Result

Agent 7 targeted command:

```bash
cd backend
uv run pytest app/tests/test_pipi_loop.py app/tests/test_harness_input_gate.py app/tests/test_answer_gate.py -q
```

Result:

```text
19 passed
```

Coordinator verification:

```bash
cd backend
uv run pytest -q -rx
uv run alembic heads
uv run alembic current
uv run ruff check app tests
uv run python ../scripts/benchmark_quality_report.py \
  --benchmark ../benchmarks/pipi_onsite_500_v1.json \
  --out /tmp/pipi-quality-check
```

Result:

```text
pytest: 244 collected, all passed
alembic heads: 0007_agent_prompt_configs (head)
alembic current: 0007_agent_prompt_configs (head)
ruff: All checks passed
quality report: generated 7 files
```

Benchmark distribution now matches the requested 500-case groups:

```text
smalltalk_app_help_unknown: 50
area_food: 100
venue_order: 90
travel_shopping: 80
product_decision: 60
help_card_update: 60
one_liner_finalize: 40
edge_adversarial: 20
```

## Unfinished Items

1. Decide whether to keep `DbPipiAbilityCenter -> DbToolExecutor` as the
   canonical DB-backed product AbilityCenter implementation, or migrate the
   product path to the generic `app.ability.center.AbilityCenter` wrapper.
2. Remove or more loudly deprecate old `PipiChatGraph` business-node exports.
3. Add a product-path database test that reads `AgentRun.output_json.loop_trace`
   after `/v1/chat/turn` and verifies all harness events.
4. Review eval/smoke bypasses at the top of `run_chat_turn` so they cannot mask
   product runtime failures during real benchmark runs.
5. Finish cleanup of legacy card model/serializer fields after compatibility
   consumers are migrated.

## Next LLM Integration Point

The next real LLM should be integrated behind `backend/app/agent/model_adapter.py`
and the `Reasoner` contract. It must still output only `tool` or `answer`, and
tool execution must remain behind the AbilityCenter boundary. A model must not
directly emit final recommendation-card/help-card JSON or bypass `PipiLoop`.
