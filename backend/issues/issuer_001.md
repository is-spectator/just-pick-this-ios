# issuer_001.md

## 失败结论

本轮未通过。

Iter Group 1 / `issuer_000` 已复验通过：

```bash
cd backend
uv run pytest app/tests/test_p0_smalltalk_state_flow.py -q -rx
```

结果：

```text
5 passed
```

进入 Iter Group 2：LangGraph checkpoint 后，当前实现未满足设计要求：

1. `/v1/chat/turn` 调用 `PipiChatGraph.invoke(...)` 时没有传 `configurable.thread_id`。
2. `build_pipi_chat_graph` 没有 checkpointer 配置入口，无法用 LangGraph checkpointer 创建 checkpoint。

## 失败测试

- `test_pipi_graph_uses_conversation_thread_id`
- `test_graph_checkpoint_created_for_chat_turn`

## 失败原因

### 1. graph.invoke 未传 thread_id

`backend/app/services/chat.py` 当前调用：

```python
state = build_pipi_chat_graph().invoke({...})
```

新增测试用 fake graph 捕获 `invoke` 的第二个参数，实际结果是：

```text
invoke_config is None
```

设计要求是：

```python
{
    "configurable": {
        "thread_id": conversation_id,
    }
}
```

### 2. graph compile 没有 checkpointer 入口

`backend/app/agent/pipi_chat_graph.py` 当前函数签名：

```python
def build_pipi_chat_graph() -> Any:
```

新增测试尝试使用最小 LangGraph `MemorySaver`：

```python
checkpointer = MemorySaver()
graph = build_pipi_chat_graph(checkpointer=checkpointer)
```

实际失败：

```text
TypeError: build_pipi_chat_graph() got an unexpected keyword argument 'checkpointer'
```

这说明当前没有 adapter 层或配置入口可以把 checkpointer 传给 `graph.compile(...)`。

## 复现命令

```bash
cd backend
uv run pytest app/tests/test_p1_graph_checkpoint.py -q -rx
```

完整测试：

```bash
cd backend
uv run pytest -q -rx
```

本轮实际结果：

```text
2 failed, 29 passed
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

1. `/v1/chat/turn` 调用 graph 时，必须传：

```python
{"configurable": {"thread_id": str(conversation.id)}}
```

2. `PipiChatGraph` 必须有 checkpointer 配置入口。V0 可以先支持函数参数：

```python
build_pipi_chat_graph(checkpointer=...)
```

3. 当传入 checkpointer 时，必须把它传给 LangGraph compile，例如：

```python
graph.compile(checkpointer=checkpointer)
```

4. 在没有真实 Postgres checkpointer 时，可以先使用 adapter 层或可注入 checkpointer；但测试必须能用 `MemorySaver` 验证一次 chat graph invoke 后确实产生 checkpoint。

## 禁止修改

- 不要改前端。
- 不要接真实 LLM。
- 不要接真实登录。
- 不要改推荐卡视觉。
- 不要绕过 `PipiChatGraph`。
- 不要恢复普通 `/recommend` 主入口。
- 不要删除或放宽本轮新增测试。
- 不要为了通过测试把 checkpoint 做成假的内存字段而不接入 LangGraph compile。

## 通过标准

- `uv run pytest app/tests/test_p1_graph_checkpoint.py -q -rx` 通过。
- `uv run pytest app/tests/test_p0_smalltalk_state_flow.py -q -rx` 继续通过。
- `uv run pytest -q -rx` 通过。
- `uv run alembic heads` 输出单一 head：`0003_card_image_fk (head)`。
- `uv run alembic current` 输出当前版本：`0003_card_image_fk (head)`。
- fake graph 捕获到的 `invoke_config` 精确等于：

```python
{
    "configurable": {
        "thread_id": conversation_id,
    }
}
```

- `MemorySaver.get_tuple({"configurable": {"thread_id": thread_id}})` 能拿到 checkpoint。
