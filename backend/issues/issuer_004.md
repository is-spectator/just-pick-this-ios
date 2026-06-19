# issuer_004.md

## 失败结论

本轮未通过。

Iter Group 4 / `issuer_003` 已复验通过：

```bash
cd backend
uv run pytest app/tests/test_p3_finalize_tool_chain.py -q -rx
```

结果：

```text
1 passed
```

进入 Iter Group 5：Intent taxonomy 对齐后，当前 intent enum 和 deterministic 分类/路由仍未符合设计。

## 失败测试

- `test_intent_taxonomy_matches_design`
- `test_korea_niche_can_route_to_help_request`
- `test_budget_feedback_routes_to_update_help_card`
- `test_one_liner_routes_to_one_liner_answer_when_in_answer_context`

## 失败原因

### 1. `PipiIntent` Literal 未对齐设计

设计要求：

```text
greeting
smalltalk
app_help
decision_request
help_request
update_help_card
publish_help
one_liner_answer
finalize_request
unknown
```

当前实际：

```text
greeting
smalltalk
app_help
decision_request
publish_help
human_evidence
finalize_request
unknown
```

差异：

```text
extra: human_evidence
missing: help_request, update_help_card, one_liner_answer
```

### 2. 韩国小众求助被压成 `decision_request`

输入：

```text
在韩国逛街，不想去明洞，想小众，求一个。
```

当前分类：

```text
decision_request
```

期望：

```text
help_request
```

它仍可以路由到 `draft_help_card`，但 intent taxonomy 必须显式表达这是求助请求，而不是普通决策请求。

### 3. 已有 active help card 后的约束补充没有进入 `update_help_card`

输入：

```text
预算不高，别太远，不要游客区，也想买美妆。
```

在已有 `active_help_card_id` 的上下文下，当前分类：

```text
unknown
```

期望：

```text
update_help_card
```

并且应路由到 `update_help_card` tool。

### 4. one-liner answer context 仍是 `human_evidence`

输入：

```text
来一句：去圣水，比明洞更适合买小众品牌。
```

在 `help_card_id` / `answer_context=True` 的上下文下，当前分类：

```text
human_evidence
```

期望：

```text
one_liner_answer
```

并且应路由到 `submit_one_liner_answer` tool。语义仍然是 human evidence，但 intent 名称必须对齐设计。

## 复现命令

```bash
cd backend
uv run pytest app/tests/test_p4_intent_taxonomy.py -q -rx
```

完整测试：

```bash
cd backend
uv run pytest -q -rx
```

本轮实际结果：

```text
4 failed, 36 passed
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

1. `app.agent.state.PipiIntent` 必须精确包含设计 intent 集合：
   - `greeting`
   - `smalltalk`
   - `app_help`
   - `decision_request`
   - `help_request`
   - `update_help_card`
   - `publish_help`
   - `one_liner_answer`
   - `finalize_request`
   - `unknown`
2. 从 intent enum 中移除审计语义不一致的 `human_evidence`，或仅作为内部字段，不作为 `PipiIntent`。
3. 韩国/明洞/小众/求一个必须分类为 `help_request`，并继续路由到 `draft_help_card`。
4. 已有 active help card 后，用户补充预算、距离、游客区、美妆等约束时，必须分类或路由为 `update_help_card`，并调用 `update_help_card` tool。
5. one-liner answer context 下的“来一句”必须分类为 `one_liner_answer`，并调用 `submit_one_liner_answer` tool。
6. OpenAI adapter 的允许 intent 列表和 system prompt 也要同步设计名称，不能继续只允许 `human_evidence`。

## 禁止修改

- 不要改前端。
- 不要接真实 LLM。
- 不要接真实登录。
- 不要改推荐卡视觉。
- 不要绕过 `PipiChatGraph`。
- 不要删除或放宽本轮新增测试。
- 不要把 `help_request` 继续隐藏在 `decision_request` 里。
- 不要把 `one_liner_answer` 继续命名为 `human_evidence` 写入 intent。

## 通过标准

- `uv run pytest app/tests/test_p4_intent_taxonomy.py -q -rx` 通过。
- `uv run pytest app/tests/test_p3_finalize_tool_chain.py -q -rx` 继续通过。
- `uv run pytest app/tests/test_p2_finalize_graph_path.py -q -rx` 继续通过。
- `uv run pytest app/tests/test_p1_graph_checkpoint.py -q -rx` 继续通过。
- `uv run pytest app/tests/test_p0_smalltalk_state_flow.py -q -rx` 继续通过。
- `uv run pytest -q -rx` 通过。
- `uv run alembic heads` 输出单一 head：`0003_card_image_fk (head)`。
- `uv run alembic current` 输出当前版本：`0003_card_image_fk (head)`。
- `PipiIntent` 与设计集合精确相等。
- 韩国小众求助分类为 `help_request`。
- active help card 下约束补充分类/路由为 `update_help_card`。
- one-liner context 下“来一句”分类为 `one_liner_answer`。
