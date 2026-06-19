# next_step_verification_report.md

## 结论

本轮“遗留风险清理 + 产品路径验真 + eval/smoke 防绕过”通过。

当前 `/v1/chat/turn` 常规请求默认走 product runtime；eval/smoke bypass 已被显式开关和显式 opt-in 保护。PipiLoop 仍是 product path 的唯一单轮 agent engine，DbPipiAbilityCenter 是当前生产路径的 AbilityCenter implementation。

## 1. 当前 `/v1/chat/turn` 真实调用链

入口：

```text
FastAPI /v1/chat/turn
-> app.services.chat.run_chat_turn
-> should_use_eval_runtime / should_use_smoke_runtime guard
-> session_scope
-> resolve conversation/user
-> persist user Turn
-> InputGate
-> optional Question creation only when gate allows
-> create AgentRun
-> DbKnowledgeRetriever
-> DbConversationContextProvider
-> DbToolExecutor internal helper
-> DbPipiAbilityCenter
-> build_pipi_chat_graph().ainvoke(..., configurable.thread_id=conversation_id)
-> PipiChatGraph wrapper nodes
   persist_turn
   input_gate
   build_context
   run_pipi_loop
   persist_response
-> PipiLoop
   Reasoner
   DbPipiAbilityCenter
   ToolResult
   Evaluator
   Reasoner
   Answer
-> AnswerGate
-> persist assistant Turn
-> persist AgentRun.output_json.loop_trace
-> return ui_events + metadata.loop
```

`PipiChatGraph` 当前只承担外层 wrapper/checkpoint 职责，不再把旧 retrieve/decide/execute/respond 业务节点放进 compiled graph 主路径。

## 2. `runtime_path` 规则

响应 `metadata.runtime_path` 现在有三种：

```text
product
eval_bypass
smoke_bypass
```

默认规则：

- 常规 `/v1/chat/turn` 一律返回 `runtime_path=product`。
- 即使 payload 看起来像 benchmark，例如带 `source=pipi-eval-lab`、`mode=remote_smoke`、`benchmark_case_id`，只要没有显式 opt-in，也必须走 product path。

`eval_bypass` 条件：

- `ALLOW_EVAL_BYPASS=true`
- `PIPI_EVAL_MODE=true`
- payload 显式 opt-in：`client_context.pipi_eval_mode=true`、`metadata.pipi_eval_mode=true` 或 `metadata.headers["x-pipi-eval-mode"]=true`
- 且来源是 `source=pipi-eval-lab`、`device_uid` 以 `eval-` 开头，或 `platform=eval`

`smoke_bypass` 条件：

- `ALLOW_EVAL_BYPASS=true`
- payload 显式 opt-in：`client_context.pipi_eval_mode=true`、`metadata.pipi_eval_mode=true` 或 `metadata.headers["x-pipi-eval-mode"]=true`
- `client_context.source=manual`
- `client_context.mode=remote_smoke`
- 不能是 `source=pipi-eval-lab`，且 `device_uid` 不能以 `eval-` 开头

QA 备注：本轮只修正了旧 `tests/test_remote_smoke_contract.py` 的测试配置，让它按新 guardrail 显式 opt-in 到 smoke bypass；未改业务代码。

## 3. PipiLoop 是否仍是唯一 product agent engine

是。

product path 中，`run_chat_turn` 创建 DB-backed runner 后，通过 `build_pipi_chat_graph().ainvoke(...)` 进入 wrapper graph，再由 `run_pipi_loop` 节点调用 `PipiLoop.run`。单轮 reasoner/tool/evaluator/answer 循环只在 PipiLoop 内完成。

主路径不使用 `DeferredAbilityCenter`。`DeferredAbilityCenter` 只保留为直接 graph/dev/test fallback，不出现在 product response metadata 或 product loop trace 中。

## 4. DbPipiAbilityCenter / DbToolExecutor 边界

当前 canonical product boundary：

```text
DbPipiAbilityCenter = product path AbilityCenter implementation
DbToolExecutor = DbPipiAbilityCenter 内部 DB mutation helper
generic AbilityCenter = schema/permission wrapper，供后续迁移和单元测试使用
```

边界规则：

- API、Graph、Reasoner 不应直接调用 `DbToolExecutor`。
- product tool execution 入口是 `DbPipiAbilityCenter.call(...)`。
- `DbToolExecutor` 只负责在该边界内部落库/更新卡片、求助卡、发布、亮灯等 DB mutation。

相关合同测试已覆盖：

- 大同 case 产生 `ToolCall`。
- 主路径没有直接调用 `DbToolExecutor`。
- response/trace 不出现 `DeferredAbilityCenter`。
- `search_knowledge` ToolResult 会被下一轮 reasoner 读取并继续 `create_recommendation_card`。

## 5. old graph nodes 是否已从主 path 清理

已清理出主 path。

`build_pipi_chat_graph()` compiled graph 节点只允许：

```text
persist_turn
input_gate
build_context
run_pipi_loop
persist_response
```

旧业务节点：

```text
rewrite_query
retrieve_knowledge
evaluate_evidence
decide_next_action
execute_tool
respond
```

已经移入 deprecated 区域或兼容别名，不再由 `backend/app/agent/__init__.py` 默认 export，也不出现在主 graph node list。

## 6. product-path loop_trace DB test

通过。

新增 DB 级 product path 测试验证：

- 大同喜晋道：
  - 真实 `/v1/chat/turn`
  - DB `AgentRun.output_json.loop_trace` 存在
  - trace 包含 `input_gate_result/context_pack/reasoner_decision/tool_call/tool_result/evaluator_result/answer_gate_result`
  - `metadata.loop.tool_calls == ["search_knowledge", "create_recommendation_card"]`
  - 返回 `show_recommendation_card`

- 韩国小众：
  - trace 完整
  - `metadata.loop.tool_calls == ["search_knowledge", "draft_help_card"]`
  - 返回 `show_help_card_draft`

- 你好：
  - Turn 落库
  - 不新增 Question
  - 不新增 ToolCall
  - 不新增 RetrievalRun
  - `ui_events=[]`
  - `loop.tool_calls=[]`

## 7. eval/smoke bypass guardrail

通过。

测试覆盖：

- 常规请求不进入 eval bypass。
- benchmark-looking payload 没有显式 opt-in 时走 product path。
- 显式 eval opt-in 且 `ALLOW_EVAL_BYPASS=true` 才能走 eval bypass。
- `ALLOW_EVAL_BYPASS=false` 时，即使显式 opt-in 也不能 bypass。
- 显式 smoke opt-in 且 `ALLOW_EVAL_BYPASS=true` 才能走 smoke bypass。
- `metadata.runtime_path` 正确标记。

## 8. RecommendationCard v2 contract

通过。

当前默认 card serializer / response schema：

- 默认返回 v2 minimal contract：
  - `item`
  - `decision_factor`
  - `image` optional
  - evidence/provenance fields
- 默认不返回：
  - `reasons`
  - `bullets`
  - `followups`
  - `warning`
- `create_recommendation_card` tool 拒绝 legacy 展示字段。
- storage 中遗留字段不会穿透到 `/v1/cards/{id}` 默认响应。

legacy DB 字段仍保留以兼容历史数据，已在 `backend/issues/legacy_card_fields_plan.md` 中标记为 deprecated 和后续 migration 候选。

## 9. 验收命令

```bash
cd backend
uv run pytest -q -rx
uv run alembic heads
uv run alembic current
uv run ruff check app tests
uv run python ../scripts/benchmark_quality_report.py --benchmark ../benchmarks/pipi_onsite_500_v1.json --out /tmp/pipi-quality-check
```

结果：

```text
pytest: 264 tests collected; full run passed
alembic heads: 0007_agent_prompt_configs (head)
alembic current: 0007_agent_prompt_configs (head)
ruff: All checks passed
quality report: generated all expected files under /tmp/pipi-quality-check
```

生成的 quality report 文件：

```text
/tmp/pipi-quality-check/quality_report.json
/tmp/pipi-quality-check/quality_report.md
/tmp/pipi-quality-check/case_quality_scores.jsonl
/tmp/pipi-quality-check/low_quality_cases.md
/tmp/pipi-quality-check/seed_gap_report.md
/tmp/pipi-quality-check/pipi_agent_improvement_report.md
/tmp/pipi-quality-check/benchmark_coverage_report.md
```

## 10. 未完成事项

1. `DbPipiAbilityCenter` 仍是 product canonical implementation，generic `AbilityCenter` 暂未完全替换 DB-backed boundary。这是刻意保留的低风险状态，后续迁移需要单独做。
2. 旧 graph business node 函数仍以 deprecated/compat 形式存在，未物理删除，避免破坏旧测试或外部 import。
3. legacy DB 字段如 `bullets_json`、`warning` 仍在模型/迁移中保留，当前只做读写隔离和默认响应剥离，后续可 migration 删除。
4. eval/smoke bypass 仍存在，但已加显式 `ALLOW_EVAL_BYPASS` 和 opt-in guard；生产环境必须保持默认 false。
5. 真实 LLM 仍未接入，当前 reasoner/model adapter 仍是 deterministic V0。

## 11. 下一步建议

接真实 LLM 前必须先做：

1. 固定一版 product-path benchmark baseline，禁止用 eval/smoke bypass 代替 product runtime。
2. 对 500-case benchmark 跑完整 quality report，记录低分 case 和 seed gap。
3. 增加 LLM shadow mode：LLM 输出只写 trace，不影响线上 answer，用来比较 deterministic vs LLM 决策。
4. 给 ModelAdapter 增加 strict schema validation：LLM 只能输出 `ToolDecision` 或 `AnswerDecision`。
5. 给每个 LLM decision 落 trace，包括 prompt config version、model、latency、input context hash、schema validation result。
6. 先在 small traffic / eval namespace 下启用，不要直接替换 product deterministic path。

是否可以开始接 ModelAdapter：

可以开始做 ModelAdapter 接入准备，但不建议直接打开 product LLM path。当前 Harness 已具备入口、trace、quality report 和 bypass guardrail，适合先做 shadow mode，再逐步启用。
