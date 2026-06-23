# 皮皮 Agent 架构设计与自进化机制

版本：2026-05-27

本文描述「就选这个」后端里的皮皮 Agent Runtime。它不是一个普通推荐接口，也不是让大模型直接吐 UI JSON 的聊天后端；它是一个可观测、可回放、可评测、可逐步进化的 Agent Harness。

## 1. 设计目标

皮皮的产品目标很窄：用户说一句“我在哪，我想干什么”，皮皮只帮用户收成一个选择。

工程目标对应为：

- 主入口只有 `POST /v1/chat/turn`。
- 用户每句话先落库为 `Turn`。
- 推荐卡、求一个、发布、来一句、最终答案、亮灯都必须通过 tool 完成。
- 大模型只能做推理和工具选择，不能绕过工具直接写卡片。
- 每一轮都能在后台看到完整 trace。
- 每一次错误都能被评测报告定位，并转成下一轮修复或数据补充。

## 2. 总体架构

当前后端采用 Hybrid Harness：

```text
iOS App
  -> POST /v1/chat/turn
  -> FastAPI
  -> persist Turn
  -> InputGate
  -> ContextBuilder
  -> PipiChatGraph
  -> PipiLoop
     -> Reasoner
     -> AbilityCenter
     -> ToolResult
     -> Evaluator
     -> Reasoner
     -> Answer
  -> AnswerGate
  -> persist assistant Turn / AgentRun
  -> UI Events
  -> Admin Trace / Eval Reports
```

职责分层：

| 层 | 职责 |
| --- | --- |
| FastAPI | HTTP schema、用户 bootstrap、路由入口 |
| PipiChatGraph | LangGraph 外层 workflow 和 `thread_id=conversation_id` checkpoint |
| InputGate | 判断是否进入工具 loop，以及允许哪些工具 |
| ContextBuilder | 压缩会话、问题、证据和活动求助卡上下文 |
| PipiLoop | 单轮 agent engine，控制 reasoner/tool/answer 循环 |
| Reasoner | 输出 `tool` 或 `answer`，不能输出其它类型 |
| AbilityCenter | 唯一工具执行边界，做权限、schema、落库和工具调用 |
| Evaluator | 检查工具结果质量，阻止泛卡、错路由和弱证据 |
| AnswerGate | 最终输出闸门，禁止调试信息、未落库卡片和内部链路外泄 |
| TraceStore / AgentRun | 保存可回放的 loop trace |
| Eval | 生成 quality report、seed gap report、agent improvement report |

## 3. 主链路

产品路径是：

```text
run_chat_turn
  -> persist user Turn
  -> InputGate
  -> create/reuse Question when needed
  -> create AgentRun
  -> PipiChatGraph wrapper
     -> persist_turn
     -> input_gate
     -> build_context
     -> run_pipi_loop
     -> persist_response
  -> return ChatTurnResponse
```

`PipiChatGraph` 只做外层流程，不再承担旧版的 `retrieve -> decide -> execute -> respond` 业务分支。真正的 agent 单轮推理在 `PipiLoop` 中完成。

## 4. InputGate

`InputGate` 是第一道闸门。它解决“该不该进入 agent loop”的问题。

示例规则：

| 输入类型 | 行为 |
| --- | --- |
| `你好` / `哈哈` / `你是谁` | 不进 loop，不建 Question，不 retrieval，不 tool，不出卡 |
| `我现在在大同喜晋道，不知道吃什么` | 进入 loop，允许 `search_knowledge`、`create_recommendation_card`、`draft_help_card` |
| `韩国逛街，不去明洞，想小众` | 进入 loop，允许检索和求一个 |
| `发出去` | 只有存在 active help card 时允许 `publish_help_card` |
| `预算不高` / `不要游客区` | 只有存在 draft help card 时允许 `update_help_card` |

这样可以避免“闲聊也出求助卡”“信息不足也发帖”这类错误。

## 5. ContextBuilder

ContextBuilder 不把整个数据库和完整历史塞给 reasoner，而是生成一个受控的 `PipiContextPack`：

```text
PipiContextPack
  - user_message
  - conversation_summary
  - active_help_card
  - active_question
  - recent_turns, max 3
  - retrieval_summary
  - strongest_evidence, max 5
  - allowed_tools
```

这层的目标是控制上下文大小和质量，让 reasoner 看见该看的信息，不被历史噪声带偏。

## 6. PipiLoop

`PipiLoop` 是皮皮的单轮 agent engine。

Reasoner 只能输出两种 decision：

```text
ToolDecision
  type = "tool"
  tool_name
  tool_args
  reason

AnswerDecision
  type = "answer"
  message
  ui_events
  data
```

循环逻辑：

```text
for iteration in max_iters:
  decision = Reasoner.next(state)
  trace(reasoner_decision)

  if decision.type == "answer":
    gated = AnswerGate.validate(state, decision)
    trace(answer_gate_result)
    return gated answer

  tool_result = AbilityCenter.call(decision.tool_name, decision.tool_args)
  trace(tool_call)
  trace(tool_result)

  eval_result = Evaluator.evaluate_tool_result(...)
  trace(evaluator_result)

  state = state.append_tool_result(decision, tool_result, eval_result)

return safe answer
```

关键点：

- `AnswerDecision` 是正常成功退出条件。
- `ToolResult` 必须回灌给下一轮 reasoner。
- 超过最大轮数时只能安全收口，不能创建卡。
- LLM 返回非法 schema、越权工具或内部失败时，降级到 deterministic decision，并记录在 trace。

## 7. Reasoner 与 LLM 边界

当前支持两种 reasoner 模式：

1. `deterministic`
   - 用规则和本地 seed 保证 benchmark 可复现。
   - 适合测试、评测、回归保护。

2. `openai`
   - 每轮进入 OpenAI reasoner，让模型输出 `tool` 或 `answer`。
   - 仍然不能直接创建卡片。
   - 只能选择 `InputGate.allowed_tools` 中的工具。
   - 所有 side effect 仍必须经过 AbilityCenter。

设计原则是：LLM 可以变聪明，但不能变得失控。

## 8. AbilityCenter 与工具

产品路径的 DB-backed 工具边界是 `DbPipiAbilityCenter`。它负责：

- 校验 tool 是否存在。
- 校验 tool 是否被当前 turn 允许。
- 写 `ToolCall`。
- 执行工具。
- 返回 `ToolResult`。
- 将结果交还给 `PipiLoop`。

`DbToolExecutor` 是内部 helper，API、Graph、Reasoner 都不能直接调用它。

核心工具：

| Tool | 作用 |
| --- | --- |
| `search_knowledge` | 检索 intent answer、历史卡、help answer、image asset、web result |
| `create_recommendation_card` | 创建推荐卡 |
| `draft_help_card` | 创建求一个草稿 |
| `update_help_card` | 更新同一张求一个 |
| `publish_help_card` | 发布求一个 |
| `submit_one_liner_answer` | 保存来一句 |
| `finalize_help_card` | 汇总求一个答案 |
| `save_intent_answer` | 沉淀最终答案 |
| `light_user` | 亮灯通知用户 |

## 9. 推荐卡契约

推荐卡必须极简，默认只暴露：

```json
{
  "item": {
    "title": "...",
    "subtitle": "...",
    "category": "..."
  },
  "decision_factor": {
    "key": "...",
    "text": "..."
  },
  "image": null
}
```

禁止：

- `reasons[]`
- `bullets[]`
- `followups[]`
- 多个 `decision_factor`
- 猜你想问
- Top 3 / 榜单式输出
- 模型编图片 URL

普通推荐卡优先绑定 verified、displayable、`is_ai_generated=false` 的 `ImageAsset`。高德地点卡可以没有图片，但必须有 `place`、`route` 或 `action` 等可执行信息。

## 10. 求一个契约

求一个不是泛泛的社区帖子，而是当前问题的结构化求助卡。

核心字段：

```text
HelpCard
  - title
  - context
  - wants
  - avoids
  - constraints
  - reward
  - answer_stats
  - revision
```

要求：

- `title` 必须具体，不能是“北京这顿饭，求一个”。
- `context` 至少包含两个有效字段。
- `wants` 不能只写“好吃”“别让我查”。
- `avoids` 不能写“多个选项”这种产品规则。
- 用户补充约束时必须更新同一张 HelpCard，不能新建一张。

## 11. FinalizeGraph

“来一句”只是 human evidence，不是最终答案。

当 HelpCard 的答案数达到阈值：

```text
answer_count >= min_required
```

进入 `PipiFinalizeGraph`：

```text
load_help_card
-> load_answers
-> build_context
-> run finalize loop
-> create_recommendation_card
-> save_intent_answer
-> light_user
```

最终结果：

- 生成最终推荐卡。
- 写入 `IntentAnswer`，作为长期记忆。
- 写入 `LightEvent`，通知用户“有人帮你选好了”。

## 12. Trace 设计

每个 `AgentRun.output_json.loop_trace` 应包含：

```text
input_gate_result
context_pack
reasoner_decision
tool_call
tool_result
evaluator_result
answer_gate_result
shadow_reasoner_result, optional
```

运营后台和 debug trace 可以用这些事件回放一次完整推理：

```text
用户说了什么
系统判成什么 intent
为什么允许这些工具
reasoner 为什么选这个工具
工具返回了什么
Evaluator 有没有扣分
AnswerGate 有没有拦截
最终给用户看了什么
```

这就是后续优化皮皮的核心数据基础。

## 13. AnswerGate

`AnswerGate` 是最后一道用户输出闸门。

它会拦截：

- greeting 携带卡片 UI。
- answer 里夹带未落库卡片 JSON。
- `ui_events` 中的 `card_id` / `help_card_id` 不存在。
- 推荐卡不是 tool 创建。
- 求一个不是 tool 创建。
- 用户可见文案里出现内部链路词，例如 `debug`、`trace`、`runtime`、`schema`、`没有可用的工具`。

因此，LLM 即使说出内部失败信息，也不会直接透给用户。

## 14. 自进化机制

皮皮的“自进化”不是让线上模型自由改代码，也不是让 prompt 在生产里无人监管地漂移。

它是一个闭环：

```text
真实会话 / benchmark
  -> trace 落库
  -> quality scoring
  -> reports
  -> 问题归类
  -> seed / prompt / rule / tool 修复
  -> tests
  -> shadow comparison
  -> 灰度或发布
```

### 14.1 数据采集

每一次 `/v1/chat/turn` 都会沉淀：

- `Conversation`
- `Turn`
- `AgentRun`
- `ToolCall`
- `RetrievalRun`
- `RetrievalHit`
- `RecommendationCard`
- `HelpCard`
- `HelpAnswer`
- `IntentAnswer`
- `LightEvent`

这些不是日志碎片，而是可复盘的 agent 运行状态。

### 14.2 质量评分

评测报告不只看接口是否 200，而是按维度打分：

```text
intent_routing
answer_usefulness
specificity
card_contract
help_card_quality
evidence_grounding
tone
latency
```

常见问题标签：

```text
wrong_location_priority
wrong_target_type
help_card_title_too_generic
help_card_context_too_thin
help_card_wants_too_generic
decision_factor_missing
too_many_decision_factors
missing_evidence
latency_too_high
```

### 14.3 报告生成

每轮 benchmark 后可以生成：

```text
quality_report.md
seed_gap_report.md
pipi_agent_improvement_report.md
low_quality_cases.md
case_quality_scores.jsonl
shadow_comparison_report.md
```

不同报告负责不同问题：

| 报告 | 作用 |
| --- | --- |
| `quality_report` | 看整体质量和维度分 |
| `seed_gap_report` | 找“系统该知道但没有数据”的缺口 |
| `pipi_agent_improvement_report` | 找路由、工具、prompt、schema 问题 |
| `low_quality_cases` | 聚焦最差案例 |
| `shadow_comparison_report` | 比较 deterministic 与 LLM 的差异 |

### 14.4 Seed 自进化

当问题是“缺答案”时，不应该靠 prompt 硬猜。

处理方式：

```text
case fails because expected recommendation but got help_card
  -> classify as seed gap
  -> add / approve IntentAnswer
  -> add verified ImageAsset or AMap place evidence
  -> rerun benchmark
```

这让皮皮的知识库逐步变厚。

### 14.5 Prompt / Policy 热更新

运营后台支持调整运行策略，例如 `area_food_evidence_policy`。

适合热更新的内容：

- 某类口味偏好规则。
- 哪些词代表用户画像。
- 哪些 POI 类型需要拒绝。
- 证据不足时是追问还是求一个。

所有后台修改写入 `AdminAuditLog`，并且下一次 `/v1/chat/turn` 生效。

### 14.6 Shadow LLM 自进化

Shadow mode 允许接入 LLM 做“影子决策”：

```text
deterministic decision -> product answer
LLM shadow decision -> trace only
```

它不影响线上结果：

- 不调用 AbilityCenter。
- 不创建卡。
- 不创建求一个。
- 不改变 `ui_events`。
- 只写 `shadow_reasoner_result` 和 `shadow_summary`。

对比后可以发现：

- LLM 是否比规则更会识别意图。
- LLM 是否频繁选择错误工具。
- 哪些 case 适合从 deterministic 迁移到 LLM。
- 哪些 prompt 或 schema 需要收紧。

### 14.7 代码修复闭环

当报告指出系统性错误，例如：

```text
你好 -> 求一个
海底捞三里屯点菜 -> 三里屯川菜馆
广东人在望京 SOHO -> 长沙菜
```

修复路径是：

```text
写 regression test
-> 修 InputGate / Reasoner / Evaluator / Tool
-> 跑 pytest
-> 跑 benchmark
-> 更新报告
-> 发布
```

原则：先补测试，再修逻辑。不要用 smoke bypass 糊弄 product runtime。

## 15. 运行时安全边界

皮皮允许逐步引入真实 LLM，但不能牺牲边界：

- LLM 输出必须符合 `ReasonerDecision` schema。
- LLM 只能选择 `allowed_tools`。
- LLM 不能直接写数据库。
- LLM 不能生成图片 URL。
- LLM 不能直接返回推荐卡 JSON。
- LLM 失败时降级 deterministic。
- 用户输出前必须经过 AnswerGate。

这使得“智能”与“可控”可以同时存在。

## 16. 当前能力状态

已具备：

- `/v1/chat/turn` 主链路。
- Hybrid Harness。
- DB-backed AbilityCenter。
- Tool call 落库。
- Retrieval 落库。
- RecommendationCard v2 契约。
- HelpCard 结构化契约。
- PipiFinalizeGraph。
- Admin trace / debug session。
- Eval API。
- Quality report。
- Shadow LLM 对比报告。
- OpenAI product reasoner，可通过配置启用。
- Tavily 网页证据和图片候选。
- 高德 POI / route / URI 能力。

仍需持续强化：

- 更多真实餐厅、区域、点单 seed。
- 更细的证据可信度评分。
- 更稳定的 LLM prompt 版本管理。
- 线上 bad case 自动聚类。
- 从 shadow LLM 到 product LLM 的灰度策略。
- 更完整的运营审核流。

## 17. 一句话总结

皮皮不是一个“回答问题”的模型壳子。

它的核心是：

```text
InputGate 控制是否进入 loop
ContextBuilder 控制喂给 reasoner 的内容
PipiLoop 控制 reasoner/tool/answer 循环
AbilityCenter 控制工具权限和副作用
Evaluator 控制工具结果质量
AnswerGate 控制最终用户输出
TraceStore 控制回放
Eval Reports 控制进化方向
Admin Config 控制可热更新策略
```

这套设计让皮皮可以在不失控的前提下逐步变聪明：先可观测，再可评测，再可修复，最后才是可自动化进化。
