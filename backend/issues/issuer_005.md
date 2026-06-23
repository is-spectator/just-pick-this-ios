# issuer_005.md

## 失败结论

本轮未通过。

Iter Group 5 / `issuer_004` 已复验通过：

```bash
cd backend
uv run pytest app/tests/test_p4_intent_taxonomy.py -q -rx
```

结果：

```text
4 passed
```

进入 Iter Group 6：`update_help_card` 可达后，当前实现能生成 `update_help_card` tool_call 草案，但 DB executor 没有真正执行更新，并且用户补充约束时仍创建了新 `Question`。

## 失败测试

- `test_update_help_card_from_user_feedback`
- `test_update_help_card_does_not_create_new_help_card`
- `test_update_help_card_does_not_create_question`

## 失败原因

测试路径：

1. `bootstrap`
2. `/v1/chat/turn` 发送：

```text
在韩国逛街，不想去明洞，想小众，求一个。
```

3. 得到 draft `help_card_id`。
4. 记录该 conversation 下 `Question` / `HelpCard` 数量。
5. 同一 conversation 发送：

```text
预算不高，别太远，不要游客区，也想买美妆。
```

并带上：

```json
{"help_card_id": "..."}
```

当前失败表现：

### 1. HelpCard 没有被更新

`tool_calls` 里可以看到 `update_help_card`，且状态看起来是 `succeeded`，但数据库里的同一张 HelpCard 完全没变：

```text
before == after
context_text: 女生 · 小众品牌 · 美妆 · 不去游客区
payload_json: {"missing_info": ["预算", "风格偏好", "同行人"]}
```

说明 `DbToolExecutor.execute` 仍没有真正处理 `update_help_card`，只是落了一个成功状态的 ignored tool result。

### 2. API 响应没有返回更新后的同一张 HelpCard

`test_update_help_card_does_not_create_new_help_card` 中：

```text
body["help_cards"] == []
```

期望：返回同一张更新后的 `help_card_id`，便于前端刷新草稿。

### 3. update 反馈仍创建了新 Question

`test_update_help_card_does_not_create_question` 中：

```text
before question count = 1
after question count = 2
```

期望：补充预算/距离/游客区/美妆只是更新 active HelpCard，不应该新建 Question。

相关代码线索：

- `backend/app/agent/model_adapter.py` 已能把约束补充路由为 `update_help_card`。
- `backend/app/services/chat.py` 的 `DbToolExecutor.execute` 仍没有 `elif name == "update_help_card"` 分支。
- `backend/app/services/chat.py` 的 `_question_for_message` 仍会对 `update_help_card` 创建新 Question。

## 复现命令

```bash
cd backend
uv run pytest app/tests/test_p5_update_help_card_flow.py -q -rx
```

完整测试：

```bash
cd backend
uv run pytest -q -rx
```

本轮实际结果：

```text
3 failed, 40 passed
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

1. `DbToolExecutor.execute` 必须支持 `update_help_card`，不能把它当 ignored tool。
2. `update_help_card` 必须更新同一张 active/draft HelpCard：
   - `context_text` 或 `payload_json` 至少沉淀用户新增约束。
   - 更新内容应包含预算、距离、游客区、美妆等信息。
3. update 成功后，`executor.help_cards` / API `help_cards` 应返回同一张更新后的 HelpCard。
4. update 反馈不能创建新的 HelpCard。
5. update 反馈不能创建新的 Question。
6. `tool_call` 应真实反映执行结果，不能在未更新业务对象时返回 `succeeded`。

## 禁止修改

- 不要改前端。
- 不要接真实 LLM。
- 不要接真实登录。
- 不要改推荐卡视觉。
- 不要绕过 `PipiChatGraph`。
- 不要删除或放宽本轮新增测试。
- 不要通过新建 HelpCard 来伪装 update。
- 不要通过创建新 Question 来承接用户反馈。

## 通过标准

- `uv run pytest app/tests/test_p5_update_help_card_flow.py -q -rx` 通过。
- `uv run pytest app/tests/test_p4_intent_taxonomy.py -q -rx` 继续通过。
- `uv run pytest app/tests/test_p3_finalize_tool_chain.py -q -rx` 继续通过。
- `uv run pytest app/tests/test_p2_finalize_graph_path.py -q -rx` 继续通过。
- `uv run pytest app/tests/test_p1_graph_checkpoint.py -q -rx` 继续通过。
- `uv run pytest app/tests/test_p0_smalltalk_state_flow.py -q -rx` 继续通过。
- `uv run pytest -q -rx` 通过。
- `uv run alembic heads` 输出单一 head：`0003_card_image_fk (head)`。
- `uv run alembic current` 输出当前版本：`0003_card_image_fk (head)`。
- 补充反馈后：
  - `tool_calls` 包含 `update_help_card` 且真实成功。
  - 同一张 HelpCard 被更新。
  - HelpCard 数量不增加。
  - Question 数量不增加。
