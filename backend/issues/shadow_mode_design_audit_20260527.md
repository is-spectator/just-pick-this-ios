# Shadow Mode Design Audit 2026-05-27

Scope: audit only. No business code changes were made.

## Executive Summary

Current product chat path is:

`POST /v1/chat/turn` -> `run_chat_turn` -> `PipiChatGraph` wrapper -> injected `PipiLoop` -> `DeterministicReasoner.next` -> `DbPipiAbilityCenter` -> tool result -> evaluator -> next reasoner or answer.

The safest shadow-mode insertion point is around the reasoner decision boundary inside `PipiLoop`, or in the service-owned `run_db_pipi_loop` wrapper before/after `PipiLoop.run`. Shadow output should be persisted as audit data only, never converted into `ToolDecision`, `AnswerDecision`, `ToolCall`, `ui_events`, assistant turns, cards, help cards, light events, or retrieval runs used by the product answer.

## 1. 当前 deterministic reasoner 的入口在哪里？

Actual deterministic reasoner entry is `DeterministicReasoner.next(state)` in `backend/app/agent/reasoner.py:19`.

How it is reached on product path:

- `backend/app/api/routes_chat.py:25-28` maps `POST /v1/chat/turn` to `app.services.chat.run_chat_turn`.
- `backend/app/services/chat.py:169-209` builds `PipiState` and calls `PipiLoop(...).run(loop_state)` without injecting a custom reasoner.
- `backend/app/agent/pipi_loop.py:81` defaults to `DeterministicReasoner()`.
- `backend/app/agent/pipi_loop.py:92-97` calls `await self.reasoner.next(current)` each iteration.
- `backend/app/agent/pipi_chat_graph.py:487-503` confirms the compiled graph is now a thin wrapper: `persist_turn -> input_gate -> build_context -> run_pipi_loop -> persist_response`.

Important nuance: `InputGate` also uses deterministic intent classification before the loop via `get_deterministic_model_adapter().classify_intent(...)` at `backend/app/harness/input_gate.py:113-117`.

## 2. ModelAdapter 当前是否存在？是否被主链路调用？

Yes, `ModelAdapter`-style code exists in `backend/app/agent/model_adapter.py`:

- `DeterministicPipiModelAdapter` at `model_adapter.py:183-584`.
- `OpenAIPipiModelAdapter` at `model_adapter.py:588-942`.
- `get_pipi_model_adapter()` at `model_adapter.py:1118-1125`.

But product tool selection currently does not call `get_pipi_model_adapter().decide_next_action(...)`.

Observed main-chain usage:

- `InputGate` uses `get_deterministic_model_adapter().classify_intent(...)`, not `get_pipi_model_adapter()`.
- `DbPipiAbilityCenter._with_context_and_query_rewrite` uses `get_deterministic_model_adapter().rewrite_query_for_state(...)` at `backend/app/services/chat.py:1194-1209`.
- `PipiLoop` defaults to `DeterministicReasoner`; `DeterministicReasoner.next` does not delegate to `model_adapter.decide_next_action`.
- `PipiChatGraph.persist_response` can call `get_pipi_model_adapter().compose_response(...)` only if no `assistant_message` exists (`backend/app/agent/pipi_chat_graph.py:158-165`). In the normal product path, `PipiLoop` already returns an assistant message.
- Deprecated compatibility nodes still call `get_pipi_model_adapter()` (`backend/app/agent/pipi_chat_graph.py:198-484`), but they are not part of the compiled product graph.

Risk to note: `Settings.pipi_model_provider` defaults to `openai` (`backend/app/config.py:30-37`) and `.env.example` also sets `PIPI_MODEL_PROVIDER=openai`, while the product reasoner is still deterministic. `AgentRun.model_provider` is set from config at `backend/app/services/chat.py:138-149`, so this field may say `openai` even when product decisioning was deterministic.

## 3. PipiLoop 当前 ReasonerDecision schema 是什么？

`ReasonerDecision` is a discriminated Pydantic union in `backend/app/agent/schemas.py:22-36`:

- `ToolDecision`
  - `type: Literal["tool"] = "tool"`
  - `tool_name: str`
  - `tool_args: dict[str, Any]`
  - `reason: str`
- `AnswerDecision`
  - `type: Literal["answer"] = "answer"`
  - `message: str`
  - `ui_events: list[dict[str, Any]]`
  - `data: dict[str, Any]`

`PipiLoopResult` is defined at `backend/app/agent/schemas.py:55-62`:

- `message`
- `ui_events`
- `data`
- `iterations`
- `finish_reason: "answer" | "max_iters" | "answer_gate_failed"`
- `trace: list[dict[str, Any]]`
- `state: dict[str, Any]`

The loop records decision, tool call, tool result, evaluator result, and answer gate result in `backend/app/agent/pipi_loop.py:92-153`.

## 4. 当前 trace 是否能存放额外 shadow result？

Technically yes, but not as a first-class typed harness event yet.

Current trace options:

- `AgentRun.output_json` is JSONB and free-form (`backend/app/models/runtime.py:114-143`).
- `PipiLoopResult.trace` is `list[dict[str, Any]]`, so runtime does not enforce the fixed harness event literal.
- `TraceStore.record_event(event_name, payload)` accepts arbitrary `event_name` and writes into `output_json["loop_trace"]` (`backend/app/harness/trace_store.py:133-184`).

Constraints:

- `HARNESS_TRACE_EVENT_NAMES` only lists the seven canonical harness events (`backend/app/harness/trace_store.py:16-25`).
- `HarnessTraceEventName` in `backend/app/agent/schemas.py:7-15` also lists only those seven events.
- Existing product-path tests assert required event presence, not exact exclusivity (`backend/app/tests/test_product_path_trace_persistence.py:15-23,90-93`), so an extra event probably will not break those tests. Still, downstream dashboards or future schema validation may assume canonical names.

Recommendation: persist shadow data under a separate top-level `output_json["shadow_llm"]` object, and optionally add a `loop_trace` event named `shadow_llm_result` only after adding explicit tests. Keep it outside the canonical `ReasonerDecision` and product `ToolResult` flow.

## 5. AgentRun.output_json 当前结构是什么？

For product chat runs, `run_chat_turn` writes `_safe_state(state)` to `agent_run.output_json` at `backend/app/services/chat.py:269-280`.

The current product chat output shape is assembled by `_state_from_loop_result` at `backend/app/services/chat.py:367-419`. Main keys:

- `conversation_id`
- `user_turn_id`
- `user_message`
- `agent_run_id`
- `metadata`
- `intent`
- `context`
- `query_rewrite`
- `retrieval_run`
- `retrieval_hits`
- `evidence_evaluation`
- `tool_results`
- `assistant_message`
- `loop_trace`
- `loop_finish_reason`
- `loop_iterations`

The `metadata` subobject includes, among other fields, `input_gate_result`, `allowed_tools`, `latest_user_context`, `active_help_card_id`, `client_context`, `question_id`, `user_id`, and `pipi_loop_result`.

For direct non-loop answers, `output_json` still stores the graph state and `loop_trace`, but without product `tool_call` / `tool_result` events.

For finalize runs, `run_finalize_graph_for_help_card` writes `_safe_state(state)` at `backend/app/jobs/finalizer_job.py:646-689`. Its state schema is `PipiFinalizeGraphState` in `backend/app/agent/pipi_finalize_graph.py:91-110`, with keys such as:

- `help_card_id`
- `question_id`
- `conversation_id`
- `user_id`
- `agent_run_id`
- `help_card`
- `help_answers`
- `retrieval_run`
- `retrieval_hits`
- `final_answer`
- `final_recommendation_card`
- `intent_answer`
- `light_event`
- `tool_calls`
- `status`
- `warnings`
- `metadata`

## 6. 哪些地方适合挂 shadow LLM 调用？

Best candidate: `PipiLoop` reasoner boundary.

- Call deterministic `reasoner.next(current)` exactly as today.
- In parallel or immediately after it, call a shadow LLM with the same sanitized `PipiState`.
- Persist shadow decision separately.
- Return only the deterministic decision to the existing loop.

Good service-level candidate: `run_db_pipi_loop` in `backend/app/services/chat.py:169-217`.

- It already has `agent_run`, `PipiState`, `input_gate_result`, `context_pack`, and the final `loop_result`.
- It can run shadow before the loop, after the loop, or both.
- It is service-owned and can update `AgentRun.output_json` without changing tool execution.

Good audit-only candidate: after `loop_result` is available, before `agent_run.output_json = _safe_state(state)` in `backend/app/services/chat.py:243-280`.

- This is safest for a first pass because product decisions and side effects already happened.
- It is best for comparing "what would LLM have done" against actual deterministic trace.
- It cannot provide per-iteration shadow decisions unless the loop records enough input snapshots.

Lower-priority candidate: `TraceStore.record_event`.

- Useful if the project wants a uniform trace stream.
- It should be paired with tests so extra shadow events do not confuse dashboards or harness checks.

Avoid:

- Do not put shadow LLM inside `DbPipiAbilityCenter.call` where it could be confused with tool execution.
- Do not let `OpenAIPipiModelAdapter.decide_next_action` replace `DeterministicReasoner.next` on the product path during shadow mode.
- Do not write shadow output into `tool_results`, `ui_events`, or `assistant_message`.

## 7. 如何保证 shadow LLM 不影响 product answer？

Use a one-way audit boundary:

1. Product decision remains `DeterministicReasoner.next`.
2. Product tool execution remains `DbPipiAbilityCenter`.
3. Product answer remains `AnswerDecision` validated by `AnswerGate`.
4. Shadow call receives a copy of state, not the mutable `PipiState` used by the loop.
5. Shadow output is schema-validated into a separate `ShadowReasonerResult`, not into `ReasonerDecision`.
6. Shadow failures are swallowed and persisted as `status="failed"` audit records; they must not change loop finish reason or response.
7. Shadow output is persisted only under `AgentRun.output_json["shadow_llm"]` or a dedicated `shadow_llm_result` trace event.
8. Shadow output must never create `ToolCall`, `RetrievalRun`, `RecommendationCard`, `HelpCard`, `HelpAnswer`, `IntentAnswer`, or `LightEvent`.
9. Tests should monkeypatch the shadow client to throw and verify the product response, cards, tool calls, and `loop_trace` canonical events are unchanged.

## 8. 需要新增哪些 env/config？

Recommended config:

- `PIPI_SHADOW_LLM_ENABLED=false`
- `PIPI_SHADOW_LLM_PROVIDER=openai`
- `PIPI_SHADOW_LLM_MODEL=gpt-4.1-mini`
- `PIPI_SHADOW_LLM_BASE_URL=https://api.openai.com/v1`
- `PIPI_SHADOW_LLM_API_KEY=` or reuse `OPENAI_API_KEY` only if explicitly allowed
- `PIPI_SHADOW_LLM_TIMEOUT_SECONDS=5`
- `PIPI_SHADOW_LLM_SAMPLE_RATE=0.0`
- `PIPI_SHADOW_LLM_MAX_STATE_BYTES=20000`
- `PIPI_SHADOW_LLM_RECORD_PROMPT=false`
- `PIPI_SHADOW_LLM_COMPARE_DECISION=true`
- `PIPI_SHADOW_LLM_FAIL_CLOSED=false`

Keep these separate from `PIPI_MODEL_PROVIDER`. Shadow mode should not require setting `PIPI_MODEL_PROVIDER=openai`, because that name currently implies possible product routing in `get_pipi_model_adapter()`.

Also consider changing defaults or docs later so local/dev default says `deterministic` unless explicitly testing LLM paths.

## 9. 需要新增哪些测试？

Minimum test set:

- `test_shadow_disabled_noop`: with default config, no shadow key appears in `AgentRun.output_json`; product behavior unchanged.
- `test_shadow_result_persisted_without_product_effect`: fake shadow client returns a different tool decision; response, `ToolCall` rows, `RecommendationCard`/`HelpCard` rows, and `ui_events` still match deterministic output.
- `test_shadow_failure_does_not_fail_turn`: fake shadow client raises timeout/error; `/v1/chat/turn` still succeeds and persists a failed shadow audit object.
- `test_shadow_not_in_tool_results`: assert `output_json["tool_results"]` contains only real product tool results, never shadow output.
- `test_shadow_trace_event_optional_and_ordered`: if using trace events, assert canonical harness events remain present and shadow event is clearly named `shadow_llm_result`.
- `test_shadow_state_redaction`: prompt/input snapshot excludes secrets, raw env, and non-serializable service objects such as `context_provider` and `pipi_loop_runner`.
- `test_shadow_schema_validation`: malformed LLM output is stored as invalid audit data and cannot become `ToolDecision` or `AnswerDecision`.
- `test_shadow_sample_rate_zero`: enabled provider with sample rate `0.0` makes no network call.
- `test_shadow_sample_rate_one`: sample rate `1.0` makes one shadow call per configured decision boundary.
- `test_agent_run_model_provider_accuracy`: product `AgentRun.model_provider` should not misleadingly report shadow provider as product provider; if shadow is recorded, it should be under shadow metadata.

Optional deeper tests:

- Product-path integration for a recommendation-card scenario where shadow says help card.
- Product-path integration for a help-card scenario where shadow says recommendation card.
- Direct-answer greeting scenario to ensure shadow does not create cards or tool calls.
- Finalizer shadow audit for `PipiFinalizeGraph`, if shadowing final answer synthesis is in scope.

## Files Audited

- `backend/AGENTS.md`
- `backend/app/api/routes_chat.py`
- `backend/app/services/chat.py`
- `backend/app/agent/model_adapter.py`
- `backend/app/agent/reasoner.py`
- `backend/app/agent/pipi_loop.py`
- `backend/app/agent/pipi_chat_graph.py`
- `backend/app/agent/schemas.py`
- `backend/app/agent/state.py`
- `backend/app/harness/input_gate.py`
- `backend/app/harness/trace_store.py`
- `backend/app/harness/evaluator.py`
- `backend/app/harness/answer_gate.py`
- `backend/app/harness/context_builder.py`
- `backend/app/models/runtime.py`
- `backend/app/jobs/finalizer_job.py`
- `backend/app/agent/pipi_finalize_graph.py`
- `backend/app/tests/test_pipi_loop.py`
- `backend/app/tests/test_trace_store.py`
- `backend/app/tests/test_product_path_trace_persistence.py`
- `backend/app/tests/test_openai_guardrails.py`
- `backend/app/debug/routes.py`
- `backend/.env.example`
