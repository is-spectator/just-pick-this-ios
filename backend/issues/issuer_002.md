# issuer_002.md

## 失败结论

本轮未通过。

Iter Group 2 / `issuer_001` 已复验通过：

```bash
cd backend
uv run pytest app/tests/test_p1_graph_checkpoint.py -q -rx
```

结果：

```text
2 passed
```

进入 Iter Group 3：FinalizeGraph 不许旁路后，当前实现仍在 one-liner 满 3 条时从 API happy path 直接调用 `finalize_help_card_now`，没有走 `PipiFinalizeGraph`。

## 失败测试

- `test_one_liner_threshold_invokes_finalize_graph`
- `test_finalize_graph_creates_final_card`
- `test_finalize_graph_saves_intent_answer`
- `test_finalize_graph_creates_light_event`

## 失败原因

新增测试做了两件事：

1. monkeypatch `PipiFinalizeGraph.invoke`，记录是否真的进入 FinalizeGraph。
2. monkeypatch `app.services.help_feed.finalize_help_card_now`，如果 API one-liner threshold 直接调用它就立刻失败。

当前第三条 one-liner 触发 threshold 时，实际路径是：

```text
POST /v1/help-cards/{id}/one-liner
-> app.services.help_feed.create_one_liner
-> create_tool_call(name="finalize_recommendation")
-> finalize_help_card_now(...)
```

失败堆栈落点：

```text
app/services/help_feed.py:96
final_card = finalize_help_card_now(session, help_card=help_card, agent_run=tool_call.agent_run, tool_call=tool_call)
```

测试错误：

```text
AssertionError: API one-liner threshold must invoke PipiFinalizeGraph, not finalize_help_card_now
```

这证明满 3 条后的 API happy path 仍是同步旁路函数，而不是 `PipiFinalizeGraph`。

## 复现命令

```bash
cd backend
uv run pytest app/tests/test_p2_finalize_graph_path.py -q -rx
```

完整测试：

```bash
cd backend
uv run pytest -q -rx
```

本轮实际结果：

```text
4 failed, 31 passed
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

1. `create_one_liner` 在 `HelpCard.answer_count >= HelpCard.min_answers_required` 时，不能直接调用 `finalize_help_card_now`。
2. 满 3 条 one-liner 后必须进入 `PipiFinalizeGraph`，例如通过专门 runner 或 `PipiFinalizerJob` 的 DB graph 路径。
3. API happy path 需要能让测试捕获到 `PipiFinalizeGraph.invoke(...)` 被调用，且 state 中包含当前 `help_card_id`。
4. FinalizeGraph 跑完后仍必须产生最终副作用：
   - 创建最终 `RecommendationCard`
   - 写入 `IntentAnswer`
   - 写入 `LightEvent(type="final_ready")`
   - `HelpCard.final_recommendation_card_id` 指向最终卡
5. 保留 one-liner 是 human evidence 的语义；不要把第三条 one-liner 当成最终答案。

## 禁止修改

- 不要改前端。
- 不要接真实 LLM。
- 不要接真实登录。
- 不要改推荐卡视觉。
- 不要绕过 `PipiFinalizeGraph`。
- 不要删除或放宽本轮新增测试。
- 不要用另一个同步 helper 复制 `finalize_help_card_now` 的逻辑来假装通过。
- 不要恢复普通 `/recommend` 主入口。

## 通过标准

- `uv run pytest app/tests/test_p2_finalize_graph_path.py -q -rx` 通过。
- `uv run pytest app/tests/test_p1_graph_checkpoint.py -q -rx` 继续通过。
- `uv run pytest app/tests/test_p0_smalltalk_state_flow.py -q -rx` 继续通过。
- `uv run pytest -q -rx` 通过。
- `uv run alembic heads` 输出单一 head：`0003_card_image_fk (head)`。
- `uv run alembic current` 输出当前版本：`0003_card_image_fk (head)`。
- 第三条 one-liner 后：
  - `PipiFinalizeGraph.invoke` 被调用。
  - `finalize_help_card_now` 没有作为 API happy path 被调用。
  - 返回 metadata 里有 `finalization_ready=True` 和 `final_card_id`。
  - DB 中存在最终推荐卡、最终 `IntentAnswer`、`final_ready` light event。
