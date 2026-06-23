# issuer_009.md

## 失败结论

本轮未通过。

Iter Group 9 / `issuer_008` 已复验通过：

```bash
cd backend
uv run pytest app/tests/test_p8_tool_schema_alignment.py -q -rx
uv run pytest -q -rx
uv run alembic heads
uv run alembic current
```

结果：

```text
app/tests/test_p8_tool_schema_alignment.py: 2 passed
完整测试: 52 passed
alembic heads: 0003_card_image_fk (head)
alembic current: 0003_card_image_fk (head)
```

进入 Iter Group 10：API response contract 后，`/v1/chat/turn` 当前响应仍是旧 contract，缺少设计要求的一等字段和 metadata 关键字段。

## 失败测试

- `test_chat_turn_response_has_top_level_ui_events`
- `test_chat_turn_response_has_metadata_intent_agent_run_retrieval_run`

## 失败原因

### 1. `/v1/chat/turn` 缺少标准 `turn_id`

设计目标要求响应包含：

```json
{
  "conversation_id": "...",
  "turn_id": "...",
  "assistant_message": "...",
  "ui_events": []
}
```

当前响应仍使用兼容字段：

```text
user_turn_id
assistant_turn_id
```

但没有标准一等字段：

```text
turn_id
```

### 2. `ui_events` 仍在 `metadata` 中，不是一等字段

设计要求 `ui_events` 是 top-level list，允许兼容旧字段，但不能只把 UI 事件塞进 `metadata`。

当前大同推荐请求的响应中，UI event 出现在：

```text
metadata.ui_events
```

响应顶层缺少：

```text
ui_events
```

### 3. `metadata` 缺少 intent / agent_run_id / retrieval_run_id

设计目标要求：

```json
{
  "metadata": {
    "intent": {},
    "agent_run_id": "...",
    "retrieval_run_id": "..."
  }
}
```

当前响应中已有：

```text
metadata.retrieval_run.id
metadata.intent_answer
metadata.ui_events
```

但缺少：

```text
metadata.intent
metadata.agent_run_id
metadata.retrieval_run_id
```

`retrieval_run_id` 应该作为 metadata 一等 id 字段，并与 `metadata.retrieval_run.id` 对齐。

## 复现命令

```bash
cd backend
uv run pytest app/tests/test_p9_api_response_contract.py -q -rx
```

完整测试：

```bash
cd backend
uv run pytest -q -rx
```

本轮实际结果：

```text
app/tests/test_p9_api_response_contract.py: 2 failed
完整测试: 2 failed, 52 passed
```

Alembic 检查通过：

```bash
cd backend
uv run alembic heads
uv run alembic current
```

结果：

```text
0003_card_image_fk (head)
0003_card_image_fk (head)
```

## 必须修复

1. `ChatTurnResponse` schema 必须新增标准一等字段：
   - `turn_id`
   - `ui_events`
2. `/v1/chat/turn` service 返回必须填充：
   - `turn_id`
   - `ui_events`
3. `metadata` 必须填充：
   - `intent`
   - `agent_run_id`
   - `retrieval_run_id`
4. 决策请求下，`metadata.retrieval_run_id` 必须等于 `metadata.retrieval_run.id`。
5. 可以保留 `user_turn_id`、`assistant_turn_id`、`metadata.retrieval_run` 等旧字段用于兼容，但不能只依赖旧字段。
6. 闲聊请求也必须有 `metadata.intent` 和 `metadata.agent_run_id`；`metadata.retrieval_run_id` 可为 `None`。

## 禁止修改

- 不要改前端。
- 不要接真实 LLM。
- 不要接真实登录。
- 不要改推荐卡视觉。
- 不要删除或放宽本轮新增测试。
- 不要把 `ui_events` 只塞进 `metadata`。
- 不要只返回 `user_turn_id` 而不返回标准 `turn_id`。
- 不要绕过 `/v1/chat/turn` 主入口。

## 通过标准

- `uv run pytest app/tests/test_p9_api_response_contract.py -q -rx` 通过。
- `uv run pytest app/tests/test_p8_tool_schema_alignment.py -q -rx` 继续通过。
- `uv run pytest app/tests/test_p7_evidence_evaluator.py -q -rx` 继续通过。
- `uv run pytest app/tests/test_p6_layered_retrieval.py -q -rx` 继续通过。
- `uv run pytest app/tests/test_p5_update_help_card_flow.py -q -rx` 继续通过。
- `uv run pytest app/tests/test_p4_intent_taxonomy.py -q -rx` 继续通过。
- `uv run pytest app/tests/test_p3_finalize_tool_chain.py -q -rx` 继续通过。
- `uv run pytest app/tests/test_p2_finalize_graph_path.py -q -rx` 继续通过。
- `uv run pytest app/tests/test_p1_graph_checkpoint.py -q -rx` 继续通过。
- `uv run pytest app/tests/test_p0_smalltalk_state_flow.py -q -rx` 继续通过。
- `uv run pytest -q -rx` 通过。
- `uv run alembic heads` 输出单一 head：`0003_card_image_fk (head)`。
- `uv run alembic current` 输出当前版本：`0003_card_image_fk (head)`。
