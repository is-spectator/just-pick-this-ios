# issuer_003.md

## 失败结论

本轮未通过。

Iter Group 3 / `issuer_002` 已复验通过：

```bash
cd backend
uv run pytest app/tests/test_p2_finalize_graph_path.py -q -rx
```

结果：

```text
4 passed
```

进入 Iter Group 4：工具名和工具链统一后，当前最终化审计日志仍未使用标准 tool_call 名称。

## 失败测试

- `test_finalize_tool_chain_records_expected_tool_calls`

## 失败原因

测试路径：

1. 创建一张韩国小众逛街的 help card。
2. 发布 help card。
3. 提交 3 条 one-liner，触发 `PipiFinalizeGraph`。
4. 查询该 help card 对应 conversation 下 `run_type="pipi_finalize"`、`graph_name="PipiFinalizeGraph"` 的 `ToolCall.tool_name`。

当前实际记录：

```text
["create_final_recommendation_card", "save_intent_answer", "light_user"]
```

缺少标准工具名：

```text
["create_recommendation_card", "finalize_help_card"]
```

同时仍出现非标准审计工具名：

```text
create_final_recommendation_card
```

这说明 Group 3 虽然已经让 one-liner threshold 走了 `PipiFinalizeGraph`，但 FinalizeGraph 内部工具链仍沿用旧命名，审计日志不能按设计还原标准工具调用序列。

相关代码位置：

- `backend/app/agent/pipi_finalize_graph.py` 仍调用 `create_final_recommendation_card`
- `backend/app/jobs/finalizer_job.py` 的 `DbFinalizeToolInvoker` 仍按 `create_final_recommendation_card` 分发
- `backend/app/agent/state.py` / `backend/app/agent/model_adapter.py` 仍保留 `finalize_recommendation`

## 复现命令

```bash
cd backend
uv run pytest app/tests/test_p3_finalize_tool_chain.py -q -rx
```

完整测试：

```bash
cd backend
uv run pytest -q -rx
```

本轮实际结果：

```text
1 failed, 35 passed
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

1. 最终化审计日志必须记录标准工具名：
   - `finalize_help_card`
   - `create_recommendation_card`
   - `save_intent_answer`
   - `light_user`
2. `PipiFinalizeGraph` 内部创建最终推荐卡时，审计 tool_call 名称必须是 `create_recommendation_card`。
3. one-liner threshold 触发最终化时，必须记录 `finalize_help_card` 作为最终化编排 tool_call。
4. 审计日志里不能再出现：
   - `finalize_recommendation`
   - `create_final_recommendation_card`
5. 如果保留 alias 兼容旧代码，只能作为内部兼容入口；写入 `tool_calls.tool_name` 的审计名必须是标准名称。

## 禁止修改

- 不要改前端。
- 不要接真实 LLM。
- 不要接真实登录。
- 不要改推荐卡视觉。
- 不要绕过 `PipiFinalizeGraph`。
- 不要删除或放宽本轮新增测试。
- 不要把非标准名称藏进别的字段来规避审计。
- 不要恢复普通 `/recommend` 主入口。

## 通过标准

- `uv run pytest app/tests/test_p3_finalize_tool_chain.py -q -rx` 通过。
- `uv run pytest app/tests/test_p2_finalize_graph_path.py -q -rx` 继续通过。
- `uv run pytest app/tests/test_p1_graph_checkpoint.py -q -rx` 继续通过。
- `uv run pytest app/tests/test_p0_smalltalk_state_flow.py -q -rx` 继续通过。
- `uv run pytest -q -rx` 通过。
- `uv run alembic heads` 输出单一 head：`0003_card_image_fk (head)`。
- `uv run alembic current` 输出当前版本：`0003_card_image_fk (head)`。
- 第三条 one-liner 后，对应 `PipiFinalizeGraph` run 的 tool_call 名称集合：
  - 包含 `finalize_help_card`
  - 包含 `create_recommendation_card`
  - 包含 `save_intent_answer`
  - 包含 `light_user`
  - 不包含 `finalize_recommendation`
  - 不包含 `create_final_recommendation_card`
