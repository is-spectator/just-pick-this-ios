# issuer_007.md

## 失败结论

本轮未通过。

Iter Group 7 / `issuer_006` 已复验通过：

```bash
cd backend
uv run pytest app/tests/test_p6_layered_retrieval.py -q -rx
```

结果：

```text
4 passed
```

进入 Iter Group 8：Evidence Evaluator 后，当前 `PipiChatGraph` 仍没有一等 `evaluate_evidence` 节点，也没有持久化结构化 `evidence_evaluation` 输出。

## 失败测试

- `test_evidence_evaluator_allows_strong_match`
- `test_evidence_evaluator_blocks_weak_match`
- `test_evidence_evaluator_output_is_persisted`

## 失败原因

### 1. Graph 中没有 `evaluate_evidence` 节点

测试检查 `build_pipi_chat_graph` 的节点和边，当前源码只有：

```text
persist_turn
classify_intent
build_context
retrieve_knowledge
decide_next_action
execute_tool
respond
```

缺少：

```text
evaluate_evidence
```

也没有设计要求的顺序：

```text
retrieve_knowledge -> evaluate_evidence -> decide_next_action
```

### 2. 强匹配大同请求没有结构化 evidence evaluation

输入：

```text
我现在在大同喜晋道，不知道吃什么，给我推荐一个。
```

当前可以出推荐卡，但 `AgentRun.output_json` 里没有：

```json
{
  "evidence_evaluation": {
    "can_recommend": true,
    "confidence": 0.82,
    "missing_requirements": [],
    "reason": "..."
  }
}
```

这说明推荐判断仍散落在 adapter/executor 逻辑中，而不是一等证据评估节点。

### 3. 弱匹配/求助请求没有结构化阻断原因

输入：

```text
在韩国逛街，不想去明洞，想小众，求一个。
```

当前会 draft help card，但 `AgentRun.output_json` 中没有：

```json
{
  "can_recommend": false,
  "missing_requirements": ["..."],
  "reason": "..."
}
```

因此系统无法审计为什么没有推荐、为什么转为求一个。

### 4. 输出没有持久化

`AgentRun.output_json` 是当前 graph state 的持久化位置，但没有 `evidence_evaluation` 字段。测试查询当前 user turn 对应 `AgentRun.output_json`，结果缺失该字段。

## 复现命令

```bash
cd backend
uv run pytest app/tests/test_p7_evidence_evaluator.py -q -rx
```

完整测试：

```bash
cd backend
uv run pytest -q -rx
```

本轮实际结果：

```text
3 failed, 47 passed
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

1. `PipiChatGraph` 必须新增一等节点：

```text
evaluate_evidence
```

2. 节点顺序必须是：

```text
retrieve_knowledge -> evaluate_evidence -> decide_next_action
```

3. `evaluate_evidence` 输出必须写入 graph state：

```json
{
  "can_recommend": true,
  "confidence": 0.82,
  "missing_requirements": [],
  "reason": "Matched seeded intent answer and acceptable evidence."
}
```

4. 强证据大同请求应满足：

```text
can_recommend = true
confidence >= 0.7
missing_requirements = []
```

5. 弱证据/求助请求应满足：

```text
can_recommend = false
confidence < 0.7
missing_requirements 非空
```

6. `AgentRun.output_json` 必须持久化 `evidence_evaluation`，便于审计和复现。
7. 后续 `decide_next_action` 应优先依据 `evidence_evaluation`，不要继续把证据判断散落在 adapter/executor 里。

## 禁止修改

- 不要改前端。
- 不要接真实 LLM。
- 不要接真实登录。
- 不要改推荐卡视觉。
- 不要绕过 `PipiChatGraph`。
- 不要删除或放宽本轮新增测试。
- 不要只在 response metadata 临时拼字段而不进入 graph state / `AgentRun.output_json`。
- 不要继续只依赖 adapter 私有 helper 判断证据是否够。

## 通过标准

- `uv run pytest app/tests/test_p7_evidence_evaluator.py -q -rx` 通过。
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
- Graph 源码/结构可证明存在 `evaluate_evidence`，且位于 `retrieve_knowledge` 与 `decide_next_action` 之间。
- 强匹配和弱匹配都能在 `AgentRun.output_json.evidence_evaluation` 中看到结构化评估结果。
