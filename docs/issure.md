# 皮皮 Agent 后端 V0 设计审计报告

审计角色：测试工程师
审计分支：`codex/test-agent-design-audit`
审计依据：`/Users/fangnaoke/Documents/皮皮v0.1-.md` 与仓库根目录 `AGENTS.md`
审计范围：后端 Agent Runtime、数据库持久化、工具调用、FinalizeGraph、API、测试覆盖

## 结论

当前代码不是空壳，已经具备 FastAPI、SQLAlchemy/Alembic、LangGraph 主流程、主要数据表、基础工具、副作用落库和验收测试。但它还没有完整实现设计文档里的“Agent Runtime”形态。

核心差距集中在四类：

1. 闲聊和未知输入的状态流不干净：`你好` 不出卡、不调用 tool 已做到，但仍然会提前创建 `Question`。
2. 图运行不具备 LangGraph 持久化能力：没有 checkpointer，也没有用 `thread_id=conversation_id` 作为可恢复执行上下文。
3. 求助最终化路径有旁路：满 3 条“来一句”后，API 直接调用同步函数生成最终卡，没有真正走 `PipiFinalizeGraph` 的完整工具链。
4. 设计里的意图、检索层、证据评估、HelpCard 结构化字段和响应协议还没有对齐。

我判断完成度约为 60%。能跑通当前 deterministic demo，但还达不到设计文档定义的 V0 Agent Runtime。

## 已验证结果

命令：

```bash
cd backend && uv run pytest -q -rx
```

结果：

```text
........................                                                 [100%]
```

命令：

```bash
cd backend && uv run alembic heads && uv run alembic current
```

结果：

```text
0003_card_image_fk (head)
Context impl PostgresqlImpl.
Will assume transactional DDL.
0003_card_image_fk (head)
```

额外验证：发送 `你好` 后不会生成推荐卡、不会生成求一个、不会调用 tool，但会创建 `Question`。

```text
{'cards': 0, 'help_cards': 0, 'tool_calls': 0, 'question_count': 1, 'questions': [('你好', 'received')]}
```

## 设计符合项

| 设计要求 | 当前状态 | 证据 |
| --- | --- | --- |
| 主入口使用 `POST /v1/chat/turn` | 已实现 | `backend/app/api/routes_chat.py:25` |
| `/v1/bootstrap`、`/v1/help-feed`、`/v1/cards/{id}`、`/v1/light-events` 等基础接口 | 已实现 | `backend/app/api/` |
| 用户 turn 先落库 | 已实现 | `backend/app/services/chat.py:73` |
| 存在 `PipiChatGraph` 节点 | 已实现 | `backend/app/agent/pipi_chat_graph.py:147` |
| greeting/smalltalk/app_help/unknown 不调用 tool | 基本实现 | `backend/app/agent/model_adapter.py:93` |
| 大同/喜晋道 deterministic 推荐卡 | 已实现 | `backend/app/services/chat.py:193` |
| 韩国/明洞/小众 deterministic 求一个 | 已实现 | `backend/app/services/chat.py:215` |
| owner 不能回答自己的求一个 | 已实现 | `backend/app/services/help_feed.py:58` |
| tool_call、retrieval_run、retrieval_hit 可落库 | 部分实现 | 当前测试覆盖通过 |
| 推荐卡图片校验 verified 且非 AI | 部分实现 | `backend/app/services/chat.py:253` |

## 主要问题

### P0. 闲聊仍然创建 `Question`

设计要求：`你好 / 哈哈 / 你是谁` 这种闲聊不能生成推荐卡，也不能生成求一个；文档行为表还要求这类输入“不创建 Question”。

当前代码在 intent 分类前就调用 `_question_for_message`：

- `backend/app/services/chat.py:73` 创建 user turn
- `backend/app/services/chat.py:81` 立刻创建或获取 question
- `backend/app/services/chat.py:669` 除发布/最终化外，默认 `create_question_for_turn`

实际复现：`你好` 后 `Question` 表新增一行，状态为 `received`。

建议：把 intent 分类提前到 question 创建之前，或者让 `_question_for_message` 接收分类结果，只在 `decision_request/help_request/update_help_card` 等业务意图时创建 Question。

### P0. LangGraph 没有持久化 checkpoint

设计要求：LangGraph checkpoint persistence，`thread_id = conversation_id`，支持后续恢复、回放、调试。

当前 `PipiChatGraph` 直接 `graph.compile()`：

- `backend/app/agent/pipi_chat_graph.py:178`

`run_chat_turn` 调用图时也没有传 `configurable.thread_id`：

- `backend/app/services/chat.py:107`

这意味着当前 graph 是一次性同步执行，状态主要靠业务表和 `agent_run.output_json` 保存，不是 LangGraph 原生可恢复 runtime。

建议：接入 PostgreSQL/SQLAlchemy 可用的 LangGraph checkpointer，调用时传入 `{"configurable": {"thread_id": str(conversation.id)}}`。

### P0. “来一句满 3 条”没有真正走 `PipiFinalizeGraph`

设计要求：`HelpCard.answer_count >= min_required` 后，由 `PipiFinalizeGraph` 读取所有 `HelpAnswer`，合成最终推荐卡，写 `IntentAnswer`，写 `LightEvent`。来一句只是 human evidence，不是最终答案。

当前 API 路径在 `create_one_liner` 里直接调用 `finalize_help_card_now`：

- `backend/app/services/help_feed.py:86` 判断满 3 条
- `backend/app/services/help_feed.py:89` 创建一个名为 `finalize_recommendation` 的 tool_call
- `backend/app/services/help_feed.py:96` 直接调用 `finalize_help_card_now`

`finalize_help_card_now` 直接写最终卡、IntentAnswer 和 LightEvent：

- `backend/app/services/chat.py:567`
- `backend/app/services/chat.py:581`
- `backend/app/services/chat.py:608`
- `backend/app/services/chat.py:629`

虽然 `backend/app/jobs/finalizer_job.py` 里存在 `PipiFinalizeGraph` 的 DB invoker，但主 API happy path 没有使用它。

建议：`create_one_liner` 只提交 `HelpAnswer` 并触发 finalizer job/graph；最终化副作用必须由 `PipiFinalizeGraph` 顺序调用工具完成。

### P1. FinalizeGraph 工具名和设计不一致

设计里的工具链是：

- `finalize_help_card`
- `create_recommendation_card`
- `save_intent_answer`
- `light_user`

当前存在以下不一致：

- ChatGraph 使用 `finalize_recommendation`：`backend/app/agent/state.py:27`
- FinalizerJob 使用 `create_final_recommendation_card`：`backend/app/jobs/finalizer_job.py:362`
- `create_one_liner` 只记录一个 `finalize_recommendation` tool_call：`backend/app/services/help_feed.py:93`

这会导致审计日志无法按设计还原“最终答案是由哪些工具产生的”。

建议：统一工具名。最终化至少要记录 `finalize_help_card` 编排调用，以及内部 `create_recommendation_card`、`save_intent_answer`、`light_user` 的 tool_call。

### P1. 意图体系不完整

设计意图包括：

- `greeting`
- `smalltalk`
- `app_help`
- `decision_request`
- `help_request`
- `update_help_card`
- `publish_help_card`
- `one_liner_answer`
- `unknown`

当前 `PipiIntent` 是：

- `greeting`
- `smalltalk`
- `app_help`
- `decision_request`
- `publish_help`
- `human_evidence`
- `finalize_request`
- `unknown`

证据：`backend/app/agent/state.py:8`

影响：

- “韩国逛街，不去明洞，想小众”被压进 `decision_request`，再由规则决定求一个，而不是显式 `help_request`。
- “预算不高 / 别太远 / 不吃辣”这类反馈没有明确 `update_help_card` 意图。
- “来一句”被命名为 `human_evidence`，和 API `one-liner` 概念不一致。

建议：先把 intent enum、分类器、测试用例和 tool routing 对齐设计文档，再谈模型替换。

### P1. `update_help_card` 工具不可达

工具 schema 里有 `UpdateHelpCardInput`：

- `backend/app/schemas/tools.py:167`

但当前 `DeterministicPipiModelAdapter.decide_next_action` 没有任何路径会选择 `update_help_card`：

- `backend/app/agent/model_adapter.py:84`

`DbToolExecutor` 的正常分发也没有可见的 `update_help_card` 执行路径。结果是用户在求一个草稿后说“预算不高”“别去游客区”“女生小众美妆”时，系统不能通过 `/v1/chat/turn` 更新同一张 HelpCard。

建议：补 `update_help_card` intent、tool routing、DB executor 和测试：用户反馈必须更新当前 active help card，而不是新建 question/help card。

### P1. 检索层没有达到设计的 layered retrieval

设计要求检索层包括：

- `intent_answers`
- 历史 `recommendation_cards`
- 历史 `help_answers`
- `image_assets`
- user memory
- web / image search

当前 `DbKnowledgeRetriever.retrieve` 主要是 deterministic 分支：

- 大同/喜晋道：固定 seed answer 和 image，`backend/app/services/chat.py:193`
- 韩国/明洞/小众：固定 seed answer 和 image，`backend/app/services/chat.py:215`
- 其它：可选 Tavily web fallback，`backend/app/services/chat.py:243`

这不是通用 layered retrieval。`search_knowledge` 工具和独立 retrieval service 存在，但正常 chat graph 没有把它作为 tool call 使用。

建议：把 `search_knowledge` 纳入 ChatGraph 的工具调用或 retriever abstraction，并为每一层写 `retrieval_hit.source_type` 覆盖测试。

### P1. 证据评估器不是一等节点

设计要求：检索之后要有 Evidence Evaluator，判断是否有足够证据、可信度、图片、是否应该求一个。

当前证据判断散落在 deterministic adapter 和 executor 逻辑里：

- adapter 根据 `_has_card_ready_evidence` 决定是否 `create_recommendation_card`
- retriever payload 塞 `has_answer_evidence`、`has_verified_non_ai_image`

Graph 节点中没有显式 `evaluate_evidence`，也没有结构化记录为什么不能推卡。

建议：在 `retrieve_knowledge` 和 `decide_next_action` 之间增加 `evaluate_evidence` 节点，输出 `evidence_status`、`confidence`、`missing_requirements`，并落到 `agent_run.output_json` 或独立审计字段。

### P1. Tool schema 和设计结构不一致

`CreateRecommendationCardInput` 当前要求 `evidence_ids` 和 `confidence`，但缺少设计要求里的 `retrieval_run_id`：

- `backend/app/schemas/tools.py:77`

`DraftHelpCardInput` 是扁平字段：

- `backend/app/schemas/tools.py:147`

缺少设计里的：

- structured `context`
- `wants`
- `avoids`
- `constraints`
- `reason_not_confident`
- `retrieval_run_id`
- `answer_stats`
- `revision`
- `reward`

建议：schema 层先对齐设计结构，再由 DB model 的 JSON 字段或新列承接。

### P2. API 响应协议和设计不完全一致

设计响应形态强调：

- `assistant_message`
- `ui_events`
- `metadata.intent`
- `metadata.agent_run_id`
- `metadata.retrieval_run_id`

当前返回：

- `cards`
- `help_cards`
- `light_events`
- `tool_calls`
- `metadata.retrieval_run`
- `metadata.ui_events`

证据：`backend/app/services/chat.py:146`

这不一定是功能错误，但前后端协议和设计文档不一致。尤其 `ui_events` 被塞进 `metadata`，而不是作为一等输出，会让移动端对话页更难按 Agent event 渲染。

建议：保留兼容字段也可以，但增加设计要求的一等字段，并补 response contract 测试。

### P2. 推荐卡序列化仍暴露设计不想展示的字段

设计要求推荐卡只展示：

- `item.title`
- `decision_factor.text`
- `image optional`

当前 `serialize_card` 仍返回：

- `subtitle`
- `one_liner`
- `bullets`
- `warning`
- `followups`

证据：`backend/app/services/runtime.py:232`

虽然 tool payload 已有 `item` 和 `decision_factor`，但 API 仍鼓励前端继续消费旧字段。

建议：V0 响应增加严格的 `display_card` 或移除旧字段；至少测试断言推荐卡主展示字段只来自 `item` 和 `decision_factor`。

### P2. `IntentAnswer` 模型不足以承载长期记忆闭环

设计里的 `intent_answer` 是最终答案沉淀，应该支持 intent key/text、answer title/summary、constraints、source_type/source_ref_id、confidence、success/rejection feedback、last_used_at。

当前模型偏薄，主要是：

- `answer_text`
- `tags_json`
- `evidence_json`
- `priority`
- `is_active`

影响：可以证明“写入了 IntentAnswer”，但还不能证明后续能按设计做复用、排序、反馈学习。

建议：扩展 `IntentAnswer` schema，至少补 `intent_key`、`answer_title`、`answer_summary`、`constraints_json`、`source_type`、`source_ref_id`、`confidence`。

## 测试缺口

当前测试能证明 deterministic demo 路径可用，但还缺这些关键断言：

1. `你好 / 哈哈 / 你是谁 / unknown` 不创建 `Question`。
2. `update_help_card`：用户补充约束时更新同一张 active HelpCard。
3. `PipiFinalizeGraph` 是满 3 条后的实际执行路径，而不是直接函数旁路。
4. 最终化会记录多条 tool_call：`create_recommendation_card`、`save_intent_answer`、`light_user`。
5. LangGraph checkpoint 使用 `conversation_id` 作为 thread id。
6. 检索层覆盖 intent answer、历史 recommendation card、help answer、image asset、web result。
7. 无图、AI 图、未验证图、低置信度时，不能创建推荐卡，只能求一个。
8. API response contract 包含一等 `ui_events` 和 `metadata.intent/agent_run_id/retrieval_run_id`。

## 建议修复顺序

1. 先修 P0：闲聊不创建 Question、接入 LangGraph checkpoint、去掉 finalization 旁路。
2. 再补 P1：intent taxonomy、update_help_card、finalizer 工具名和工具链、Evidence Evaluator。
3. 最后补 P2：API 响应协议、HelpCard/IntentAnswer 结构化字段、推荐卡展示字段收敛。

这份代码目前适合作为“能跑的 deterministic proof of concept”，不适合标记为“设计文档 V0 已完成”。
