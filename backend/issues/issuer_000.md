# issuer_000.md

## 失败结论

本轮未通过。

Iter Group 1：P0 闲聊状态流未满足设计。`你好 / 哈哈 / 你是谁 / app_help / unknown` 这类非决策输入当前不会出推荐卡、不会出求一个、不会调用 tool、不会创建 retrieval_run，但仍然会创建 `Question`。

本 issue 以 `docs/issure.md` 为源头，聚焦审计报告里的 P0 问题：闲聊和未知输入的状态流不干净。

## 失败测试

- `test_greeting_does_not_create_question`
- `test_smalltalk_does_not_create_question`
- `test_app_help_does_not_create_question`
- `test_unknown_does_not_create_question`

保护测试已通过：

- `test_decision_request_still_creates_question`

## 失败原因

`run_chat_turn` 在调用 `PipiChatGraph` 做 intent 分类之前，就先调用 `_question_for_message` 创建了 `Question`。

当前路径：

1. `backend/app/services/chat.py` 创建 user `Turn`。
2. 立刻调用 `_question_for_message(...)`。
3. `_question_for_message` 只对发布/最终化关键词走 `latest_question`，其它输入全部调用 `create_question_for_turn(...)`。
4. Graph 后续把 `greeting / smalltalk / app_help / unknown` 直接路由到 `respond`，但此时 `Question` 已经落库。

因此新增测试看到：

```text
counts["turn_roles"] == ["user", "assistant"]
counts["question_count"] == 1
counts["tool_call_count"] == 0
counts["retrieval_run_count"] == 0
```

设计要求是：

```text
counts["question_count"] == 0
```

## 复现命令

```bash
cd backend
uv run pytest app/tests/test_p0_smalltalk_state_flow.py -q -rx
```

完整测试：

```bash
cd backend
uv run pytest -q -rx
```

本轮实际结果：

```text
4 failed, 25 passed
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

1. `你好` 不能创建 `Question`。
2. `哈哈` 不能创建 `Question`。
3. `这个 app 怎么用？` 这类 `app_help` 不能创建 `Question`。
4. `unknown` 不能创建 `Question`。
5. 以上非决策输入仍然必须只落 user/assistant `Turn`，且不创建 `ToolCall`、`RetrievalRun`、`RecommendationCard`、`HelpCard`。
6. 决策请求仍然必须创建 `Question`，例如“大同喜晋道吃什么”。

## 禁止修改

- 不要改前端。
- 不要接真实 LLM。
- 不要接真实登录。
- 不要改推荐卡视觉。
- 不要绕过 `PipiChatGraph`。
- 不要恢复普通 `/recommend` 主入口。
- 不要删除或放宽本轮新增测试。
- 不要为了通过测试关闭 `Turn` 或 `AgentRun` 落库。

## 通过标准

- `uv run pytest app/tests/test_p0_smalltalk_state_flow.py -q -rx` 通过。
- `uv run pytest -q -rx` 通过。
- `uv run alembic heads` 输出单一 head：`0003_card_image_fk (head)`。
- `uv run alembic current` 输出当前版本：`0003_card_image_fk (head)`。
- 对 `你好 / 哈哈 / app_help / unknown`：
  - `Question count = 0`
  - `ToolCall count = 0`
  - `RetrievalRun count = 0`
  - `cards = []`
  - `help_cards = []`
  - `Turn roles = ["user", "assistant"]`
- 对决策请求：
  - `Question count = 1`
