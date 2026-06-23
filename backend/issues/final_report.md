# final_report.md

## 结论

皮皮 Agent 后端已收口到 Hybrid Harness 主链路。`/v1/chat/turn` 现在经由 `PipiChatGraph` 外层 workflow/checkpoint，进入 `InputGate -> ContextBuilder -> PipiLoop -> AbilityCenter -> Evaluator -> AnswerGate`。Agent 6 曾记录的全量失败项已在 Coordinator 集成阶段修复并复测。

## 已修复问题

- P0 闲聊状态流已对齐：`你好` / `哈哈` / `你是谁` / `unknown` 只落 Turn，不创建 Question、RetrievalRun、ToolCall、推荐卡或求一个。
- PipiChatGraph 已支持 checkpoint 配置入口，并在调用时使用 `thread_id = conversation_id`。
- 来一句满 3 条后已走 PipiFinalizeGraph，不再通过 API happy path 旁路 finalize。
- 最终化 tool_call 审计链已统一为标准工具名：`finalize_help_card`、`create_recommendation_card`、`save_intent_answer`、`light_user`。
- Intent taxonomy 已包含设计要求的 intent：`greeting`、`smalltalk`、`app_help`、`decision_request`、`help_request`、`update_help_card`、`publish_help`、`one_liner_answer`、`finalize_request`、`unknown`。
- `update_help_card` 已可达：已有 draft help card 后，预算、距离、游客区、美妆等反馈会更新同一张 HelpCard，不新建 Question 或 HelpCard。
- Retrieval 已按层记录 `intent_answer`、`recommendation_card`、`help_answer`、`image_asset` 等 source_type。
- Evidence evaluation 已进入 PipiLoop 的 tool-result evaluator 阶段，并持久化 `evidence_evaluation` 输出；旧 graph 的 `evaluate_evidence` 业务节点不再作为主链路节点。
- Tool schema 已对齐：推荐卡输入收敛到 item / decision_factor / image / evidence / retrieval_run；求助卡 schema 支持结构化 context / wants / avoids / constraints / revision / reward / answer_stats。
- `/v1/chat/turn` response contract 已对齐：顶层返回 `turn_id`、`ui_events`，metadata 返回 `intent`、`agent_run_id`、`retrieval_run_id`。
- `IntentAnswer` 已补齐长期记忆字段，并且 HelpCard finalizer 会写入 `source_type="help_final"`、`source_ref_id=help_card_id` 的最终记忆。

## 仍未完成但不阻塞 V0

- V0 仍使用 deterministic model adapter，不接真实 LLM，符合当前闭环要求。
- 外网 web_result 层不依赖真实外网调用；当前验收覆盖本地可确定的 layered retrieval 行为。
- 前端、设计稿、真实登录、推荐卡视觉不在本轮修复范围内，未作为本轮验收目标。

## 测试命令

```bash
cd backend
uv run pytest app/tests/test_p10_intent_answer_memory.py -q -rx
uv run pytest app/tests/test_p9_api_response_contract.py -q -rx
uv run pytest app/tests/test_p8_tool_schema_alignment.py -q -rx
uv run pytest app/tests/test_p7_evidence_evaluator.py -q -rx
uv run pytest app/tests/test_p6_layered_retrieval.py -q -rx
uv run pytest app/tests/test_p5_update_help_card_flow.py -q -rx
uv run pytest app/tests/test_p4_intent_taxonomy.py -q -rx
uv run pytest app/tests/test_p3_finalize_tool_chain.py -q -rx
uv run pytest app/tests/test_p2_finalize_graph_path.py -q -rx
uv run pytest app/tests/test_p1_graph_checkpoint.py -q -rx
uv run pytest app/tests/test_p0_smalltalk_state_flow.py -q -rx
uv run pytest -q -rx
uv run alembic upgrade head
uv run alembic heads
uv run alembic current
```

## 结果

```text
app/tests/test_p10_intent_answer_memory.py: 2 passed
app/tests/test_p9_api_response_contract.py: 2 passed
app/tests/test_p8_tool_schema_alignment.py: 2 passed
app/tests/test_p7_evidence_evaluator.py: 3 passed
app/tests/test_p6_layered_retrieval.py: 4 passed
app/tests/test_p5_update_help_card_flow.py: 3 passed
app/tests/test_p4_intent_taxonomy.py: 4 passed
app/tests/test_p3_finalize_tool_chain.py: 1 passed
app/tests/test_p2_finalize_graph_path.py: 4 passed
app/tests/test_p1_graph_checkpoint.py: 2 passed
app/tests/test_p0_smalltalk_state_flow.py: 5 passed
完整测试: `uv run pytest -q -rx` -> 205 passed
alembic upgrade head: passed
alembic heads: 0007_agent_prompt_configs (head)
alembic current: 0007_agent_prompt_configs (head)
```

## 2026-05-27 Agent 6 QA 更新

本轮只修改测试与文档，未改业务实现文件。

### 验证矩阵

- `你好` / `你是谁` / `unknown`：`InputGate` 不进 loop、不建 Question、不 retrieval、不放行 tool；`PipiLoop` 直接 answer，且无 UI 卡片。
- 大同喜晋道：验证 `search_knowledge -> create_recommendation_card -> answer`。
- 韩国小众：验证 `search_knowledge -> draft_help_card -> answer`。
- `发出去`：无 active help card 时不调用 `publish_help_card`；有 active help card 时调用。
- `预算不高`：`update_help_card` 保持同一张 `HelpCard` ID。
- 海底捞三里屯：evaluator 要求 `in_venue + ordering_bundle`，并拒绝“三里屯川菜馆候选”泄漏。
- 推荐卡：evaluator 拒绝 `decision_factors` 或数组型 `decision_factor`，只允许一个 `decision_factor`。
- 求一个：title/context/wants/avoids 太泛时 evaluator failed。
- `ToolResult`：确认被下一轮 reasoner 看到后才进入 answer。
- `loop_trace`：确认完整记录 `input_gate_result/context_pack/reasoner_decision/tool_call/tool_result/evaluator_result/answer_gate_result`。
- FinalizeGraph：现有 `test_p2_finalize_graph_path.py` / `test_p3_finalize_tool_chain.py` 确认不是旁路函数。
- `quality_report`：确认 `quality_report.json`、`quality_report.md`、`case_quality_scores.jsonl` 可生成。

### 本轮命令结果

```text
uv run pytest app/tests/test_harness_input_gate.py app/tests/test_pipi_loop.py app/tests/test_ability_center.py app/tests/test_evaluator.py app/tests/test_answer_gate.py app/tests/test_context_builder.py app/tests/test_trace_store.py app/tests/test_quality_scoring.py app/eval/test_quality_scoring.py -q -rx
39 passed

uv run pytest app/tests/test_p2_finalize_graph_path.py app/tests/test_p3_finalize_tool_chain.py -q -rx
5 passed

uv run ruff check app/tests/test_harness_input_gate.py app/tests/test_pipi_loop.py app/tests/test_ability_center.py app/tests/test_evaluator.py app/tests/test_answer_gate.py app/tests/test_context_builder.py app/tests/test_trace_store.py app/tests/test_quality_scoring.py app/eval/test_quality_scoring.py
All checks passed
```

Agent 6 初次全量命令曾未通过：

```text
uv run pytest -q -rx
failed
```

连续复跑显示失败项受当前持久化测试状态影响会浮动；最新 `--tb=no` 摘要仍失败在以下非 Agent 6 职责文件或业务链路变更：

- `app/tests/test_amap_integration.py::test_chaoyang_soho_cantonese_profile_is_area_food_decision`：`debug.query_rewrite` 为 `None`。
- `app/tests/test_contextual_session_history.py::test_ios_request_uses_real_runtime_and_sijiminfu_ordering_beats_active_help_card`：多了 `search_knowledge` tool call。
- `app/tests/test_debug_dashboard.py::test_debug_dashboard_exposes_sessions_and_trace_details`：debug trace 节点不再包含 `rewrite_query`。
- `app/tests/test_p7_evidence_evaluator.py::*`：`evaluate_evidence` 节点 / `evidence_evaluation` 输出缺失。

首次 exact `uv run pytest -q -rx` 还暴露过 `test_contextual_session_history.py::test_followup_after_help_card_updates_active_card_instead_of_failing`、`test_p1_graph_checkpoint.py::test_graph_checkpoint_created_for_chat_turn`、`test_tavily_reference_images.py::*` 等同类主链路 / persisted evidence 输出问题。

### Coordinator 集成修复

- `/v1/chat/turn` 改为调用 `build_pipi_chat_graph().ainvoke(...)`，并显式传入 `{"configurable": {"thread_id": conversation_id}}`。
- `PipiChatGraph.run_pipi_loop` 改为调用真实 `PipiLoop` runner；旧 retrieve / decide / execute / respond 业务节点保留兼容导出，但不在主 graph path。
- `AgentRun.graph_name` 改为 `PipiChatGraph`。
- `search_knowledge` 的 `query_rewrite`、`retrieval_hits`、`evidence_evaluation` 回写到最终 `AgentRun.output_json`。
- active help card 场景下，短追问优先路由为 `update_help_card`，不再被上一轮 decision context 抢成新求助卡。
- 调整旧测试断言：四季民福点菜现在按 Harness 正确链路记录 `search_knowledge -> create_recommendation_card`，不再期望绕过检索只记一个 tool。


### 最终复测

```text
uv run pytest -q -rx
205 passed

uv run alembic heads
0007_agent_prompt_configs (head)

uv run alembic current
0007_agent_prompt_configs (head)
```
