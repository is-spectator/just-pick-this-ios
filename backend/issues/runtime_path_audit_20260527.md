# Runtime Path Audit 2026-05-27

Scope: static audit only. No business code was changed.

## Current Path

The normal product path for `POST /v1/chat/turn` is:

1. `backend/app/main.py` includes `api_router`; `backend/app/api/__init__.py` applies prefix `/v1`; `backend/app/api/routes_chat.py:25-28` maps `/chat/turn` to `app.services.chat.run_chat_turn`.
2. `backend/app/services/chat.py:88-95` has early eval/smoke bypasses. The rest of this audit describes the non-eval, non-smoke product path.
3. `run_chat_turn` persists the user `Turn` first at `backend/app/services/chat.py:99-107`, runs `InputGate` at `backend/app/services/chat.py:108-115`, conditionally creates or reuses `Question` at `backend/app/services/chat.py:116-133`, then creates `AgentRun(graph_name="PipiChatGraph")` at `backend/app/services/chat.py:134-147`.
4. The service builds `DbKnowledgeRetriever`, `DbConversationContextProvider`, and `DbToolExecutor` at `backend/app/services/chat.py:149-158`.
5. The service injects `pipi_loop_runner=run_db_pipi_loop` into graph metadata at `backend/app/services/chat.py:211-223`, then invokes `build_pipi_chat_graph()` with `thread_id=conversation_id` via `_invoke_pipi_chat_graph` at `backend/app/services/chat.py:224-234` and `backend/app/services/chat.py:325-340`.
6. The compiled `PipiChatGraph` nodes are only `persist_turn -> input_gate -> direct_answer_or_build_context -> run_pipi_loop -> persist_response`, as shown by `backend/app/agent/pipi_chat_graph.py:467-486`.
7. For turns where `InputGate.should_enter_loop` is false, `direct_answer_or_build_context` writes `assistant_message`; `run_pipi_loop` then exits through `_finish_loop_response` without calling `PipiLoop.run` (`backend/app/agent/pipi_chat_graph.py:77-95`, `backend/app/agent/pipi_chat_graph.py:109-118`).
8. For turns that enter the loop, `run_pipi_loop` calls the injected service runner (`backend/app/agent/pipi_chat_graph.py:120-127`). That runner calls `await PipiLoop(...).run(loop_state)` with `DbPipiAbilityCenter`, `Evaluator`, and `AnswerGate` at `backend/app/services/chat.py:161-201`.
9. Runtime ability execution is DB-backed: `DbPipiAbilityCenter.call` handles `search_knowledge` directly and delegates other tools to `DbToolExecutor.execute` (`backend/app/services/chat.py:1049-1144`).
10. `DbToolExecutor.execute` persists `ToolCall` rows and handles `create_recommendation_card`, `draft_help_card`, `update_help_card`, `publish_help_card`, `submit_one_liner_answer`, and `finalize_help_card` at `backend/app/services/chat.py:1189-1245`.
11. `PipiLoop.run` feeds each `ToolResult` back into `PipiState.append_tool_result` before the next reasoner iteration (`backend/app/agent/pipi_loop.py:87-149`). `DeterministicReasoner.next` checks previous tool results before choosing the next action (`backend/app/agent/reasoner.py:19-23`, `backend/app/agent/reasoner.py:73-106`, `backend/app/agent/reasoner.py:153-220`).
12. The service persists the assistant `Turn`, writes `AgentRun.output_json`, and returns the response contract at `backend/app/services/chat.py:261-315`.

Direct answers therefore pass through the `run_pipi_loop` graph node but do not call `PipiLoop.run`. Decision/help/publish/answer/finalize turns do call `PipiLoop.run` on the normal product path.

## Violations

1. `loop_trace` is not the complete Harness trace required by `backend/AGENTS.md`.
   - Required event names are declared as `input_gate_result`, `context_pack`, `reasoner_decision`, `tool_call`, `tool_result`, `evaluator_result`, and `answer_gate_result` in `backend/app/agent/schemas.py:7-15`.
   - `PipiLoop.run` records `reasoner_decision`, `tool_result`, `evaluator_result`, and `answer_gate_result`, but never records a first-class `tool_call` event (`backend/app/agent/pipi_loop.py:91-141`).
   - `PipiChatGraph` does append `input_gate_result` and `context_pack` before the inner loop (`backend/app/agent/pipi_chat_graph.py:47-67`, `backend/app/agent/pipi_chat_graph.py:97-106`), but `_merge_loop_runner_state` replaces `loop_trace` with the inner `PipiLoop` trace when one exists (`backend/app/agent/pipi_chat_graph.py:699-728`).
   - `run_chat_turn` then persists `AgentRun.output_json` from `_state_from_loop_result`, which also takes `loop_result.trace` directly (`backend/app/services/chat.py:235-272`, `backend/app/services/chat.py:387-399`).
   - Result: persisted loop turns are missing `input_gate_result`, `context_pack`, and `tool_call` as first-class trace events.

2. Main path does not use the generic `app.ability.center.AbilityCenter`.
   - The generic `AbilityCenter` does perform schema checks, permissions, hooks, and tool execution (`backend/app/ability/center.py:22-180`), and the registry builds default tools (`backend/app/ability/registry.py:33-66`).
   - `/v1/chat/turn` instead uses `DbPipiAbilityCenter` plus `DbToolExecutor` (`backend/app/services/chat.py:190-201`, `backend/app/services/chat.py:1049-1245`).
   - This is acceptable only if `DbPipiAbilityCenter` is the intended product AbilityCenter. If the architecture requires the generic AbilityCenter to be the sole boundary, the main path still bypasses it.

3. `DeferredAbilityCenter` is not on the normal service path, but it remains a real fallback.
   - `PipiLoop` defaults to `DeferredAbilityCenter` when no ability center is injected (`backend/app/agent/pipi_loop.py:80-82`, `backend/app/agent/pipi_loop.py:159-182`).
   - `PipiChatGraph.run_pipi_loop` invokes `PipiLoop(max_iters=2)` without an injected DB ability center when no `pipi_loop_runner` is present (`backend/app/agent/pipi_chat_graph.py:129-155`).
   - Normal `/v1/chat/turn` injects the runner, so this is not a product happy-path violation. It is still a direct-graph/test/dev path risk because tool calls become skipped/deferred results.

4. `AnswerDecision` is not the unique exit condition.
   - Normal successful loop exit is `AnswerDecision` plus passing `AnswerGate` (`backend/app/agent/pipi_loop.py:98-120`).
   - `PipiLoop.run` can also exit via `answer_gate_failed` and `max_iters` (`backend/app/agent/pipi_loop.py:104-111`, `backend/app/agent/pipi_loop.py:143-149`).
   - Non-loop direct answers bypass `PipiLoop.run` entirely and finish in the graph wrapper (`backend/app/agent/pipi_chat_graph.py:112-118`).

5. `PipiChatGraph` no longer executes the old business nodes, but stale functions remain.
   - Old functions still exist: `rewrite_query`, `retrieve_knowledge`, `evaluate_evidence`, `decide_next_action`, `execute_tool`, and `respond` at `backend/app/agent/pipi_chat_graph.py:198-309` and `backend/app/agent/pipi_chat_graph.py:449-464`.
   - They are not added to the compiled graph. The compiled graph only adds `persist_turn`, `input_gate`, `direct_answer_or_build_context`, `run_pipi_loop`, and `persist_response` (`backend/app/agent/pipi_chat_graph.py:472-483`).
   - Some old behavior survives as helper logic: context building happens inside `direct_answer_or_build_context`; query rewrite and retrieval happen inside `DbPipiAbilityCenter._search_knowledge`; evidence evaluation is reconstructed in service state from hits.

6. Response contract is current but mixed.
   - Schema fields are `conversation_id`, `turn_id`, `user_turn_id`, `assistant_turn_id`, `assistant_message`, `response_kind`, `location_state`, `ui_events`, `data`, `debug`, `cards`, `help_cards`, `light_events`, `tool_calls`, and `metadata` (`backend/app/schemas/chat.py:76-91`).
   - Service returns those fields at `backend/app/services/chat.py:302-315`.
   - `metadata` includes `intent`, `agent_run_id`, `retrieval_run_id`, `retrieval_run`, `input_gate`, and loop summary (`backend/app/services/chat.py:280-288`).
   - `response_kind` is coarse: any help-card output is reported as `help_card_draft`, including updated or published help cards (`backend/app/services/chat.py:1806-1815`). This may be fine for V0, but it is not a precise runtime-action contract.

7. `final_report.md` is partially stale and should not be treated as authoritative.
   - It claims the full harness trace includes `input_gate_result/context_pack/reasoner_decision/tool_call/tool_result/evaluator_result/answer_gate_result` (`backend/issues/final_report.md:82-83`), which does not match the persisted loop path above.
   - It says the runtime enters `PipiLoop -> AbilityCenter` (`backend/issues/final_report.md:5`), but the product path uses `DbPipiAbilityCenter` and `DbToolExecutor`, not the generic `app.ability.center.AbilityCenter`.
   - It claims old graph business nodes are no longer the path (`backend/issues/final_report.md:118-121`), which is mostly true, but debug/test files still contain old graph-node expectations such as `rewrite_query` and `evaluate_evidence` (`backend/app/tests/test_debug_dashboard.py:42-43`).
   - The report contains conflicting historical test status blocks: full suite passed at `backend/issues/final_report.md:62`, failed at `backend/issues/final_report.md:103-114`, and passed again at `backend/issues/final_report.md:128-130`.

## Files to Fix

1. `backend/app/agent/pipi_loop.py`
   - Add a first-class `tool_call` trace event before ability execution, or wire `TraceStore.record_tool_call` into the loop.
   - Decide whether `answer_gate_failed` and `max_iters` are allowed terminal states or must become explicit `AnswerDecision` fallback decisions.

2. `backend/app/agent/pipi_chat_graph.py`
   - Merge graph-level `loop_trace` events with inner loop trace in `_merge_loop_runner_state` instead of replacing them.
   - Decide whether direct-answer path should also be represented as a normal `AnswerDecision` event.
   - Consider removing or clearly marking old exported functions if they are not production nodes.

3. `backend/app/services/chat.py`
   - Preserve full trace into `AgentRun.output_json`.
   - Decide whether product tool execution should remain `DbPipiAbilityCenter -> DbToolExecutor` or be routed through the generic `AbilityCenter`.
   - If the response contract needs action-level precision, split `help_card_draft` from `help_card_updated` and `help_card_published`.

4. `backend/app/harness/trace_store.py`
   - If TraceStore is the canonical trace contract, wire it into the product `PipiLoop` path instead of only testing it independently.

5. `backend/app/tests/test_debug_dashboard.py`
   - Update old graph-node assertions. The current graph no longer contains `rewrite_query` or `evaluate_evidence` nodes.

6. `backend/issues/final_report.md`
   - Mark stale sections or replace with a fresh report after the trace and AbilityCenter decisions are fixed.

## Required Tests

1. Product-path trace test for `/v1/chat/turn` decision request:
   - Assert persisted `AgentRun.output_json["loop_trace"]` contains, in order, at least `input_gate_result`, `context_pack`, `reasoner_decision`, `tool_call`, `tool_result`, `evaluator_result`, second `reasoner_decision`, and `answer_gate_result`.

2. Product-path ability boundary test:
   - Assert `/v1/chat/turn` does not use `DeferredAbilityCenter`.
   - Assert each selected tool creates a persisted `ToolCall` and the matching domain row/card/help-card/help-answer/light-event where applicable.

3. ToolResult feedback regression:
   - Keep the existing unit assertion that the second Reasoner call sees the first tool result.
   - Add an API-level variant that proves `search_knowledge` result is visible before `create_recommendation_card` or `draft_help_card`.

4. Graph topology test:
   - Assert `build_pipi_chat_graph()` compiled/source path contains `run_pipi_loop` and does not add old `rewrite_query`, `retrieve_knowledge`, `evaluate_evidence`, `decide_next_action`, `execute_tool`, or `respond` nodes.

5. Direct-answer test:
   - Assert greeting/smalltalk persists user and assistant turns, creates no Question/RetrievalRun/ToolCall/card/help-card, and records a deliberate direct-answer trace shape.

6. Response contract tests:
   - Assert top-level `turn_id`, `ui_events`, `data`, `tool_calls`, and `metadata.agent_run_id/retrieval_run_id/intent` are present for card and help paths.
   - If action-level response kinds are required, add tests for `help_card_updated` and `help_card_published`.

7. Debug dashboard test:
   - Replace old graph-node expectations with the current harness events and persisted tool/retrieval rows.

## Risk Level

Medium-high.

The main product path has moved to `PipiChatGraph` as an outer wrapper around `PipiLoop.run`, and DB-backed tools are genuinely executed. The remaining risk is not that cards are purely model-generated or in-memory; the larger risk is auditability and contract drift: persisted `loop_trace` is incomplete, the generic `AbilityCenter` is not the product boundary, `DeferredAbilityCenter` can still appear in direct graph fallback paths, and `final_report.md` overstates the current state.
