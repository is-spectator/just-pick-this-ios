# issuer_010.md

## 失败结论

本轮未通过。

Iter Group 10 / `issuer_009` 已复验通过：

```bash
cd backend
uv run pytest app/tests/test_p9_api_response_contract.py -q -rx
uv run pytest -q -rx
uv run alembic heads
uv run alembic current
```

结果：

```text
app/tests/test_p9_api_response_contract.py: 2 passed
完整测试: 54 passed
alembic heads: 0003_card_image_fk (head)
alembic current: 0003_card_image_fk (head)
```

进入 Iter Group 11：IntentAnswer 长期记忆字段后，当前 `IntentAnswer` 仍是短期答案/证据结构，缺少设计要求的长期记忆字段；finalizer 也没有按 `source_type/source_ref_id` 写入 help final 记忆。

## 失败测试

- `test_intent_answer_has_memory_fields`
- `test_finalizer_writes_help_final_intent_answer`

## 失败原因

### 1. `IntentAnswer` 模型缺少长期记忆字段

设计要求 `IntentAnswer` 至少包含：

```text
intent_key
intent_text
answer_title
answer_summary
constraints_json
source_type
source_ref_id
confidence
success_count
rejection_count
last_used_at
```

当前 SQLAlchemy model columns 仍主要是：

```text
id
intent_id
image_asset_id
answer_text
locale
tags_json
evidence_json
priority
is_active
created_at
updated_at
```

缺少上述长期记忆字段，因此 DB inspector 检查也无法通过。需要新增 Alembic migration，把表结构与模型一起对齐。

### 2. Finalizer 写入仍依赖 `evidence_json`

设计要求来一句满 3 条后，最终化写入的长期记忆应可通过：

```text
source_type = "help_final"
source_ref_id = help_card_id
```

查到，并且填充：

```text
intent_key
intent_text
answer_title
answer_summary
confidence
success_count = 0
rejection_count = 0
```

当前实现仍把 help final 来源沉淀在：

```text
evidence_json.source_type
evidence_json.help_card_id
```

并且 `IntentAnswer.source_type` / `IntentAnswer.source_ref_id` 属性不存在，行为测试直接失败为：

```text
AttributeError: type object 'IntentAnswer' has no attribute 'source_type'
```

## 复现命令

```bash
cd backend
uv run pytest app/tests/test_p10_intent_answer_memory.py -q -rx
```

完整测试：

```bash
cd backend
uv run pytest -q -rx
```

本轮实际结果：

```text
app/tests/test_p10_intent_answer_memory.py: 2 failed
完整测试: 2 failed, 54 passed
```

Alembic 检查通过，但仍停留在旧 head：

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

1. 在 `IntentAnswer` SQLAlchemy model 上新增长期记忆字段：
   - `intent_key`
   - `intent_text`
   - `answer_title`
   - `answer_summary`
   - `constraints_json`
   - `source_type`
   - `source_ref_id`
   - `confidence`
   - `success_count`
   - `rejection_count`
   - `last_used_at`
2. 新增 Alembic migration，将 `intent_answers` 表补齐上述列。
3. migration 应设置合理默认值或 nullable 策略，保证现有 seed/runtime 数据可升级。
4. PipiFinalizeGraph / finalizer 写入 help final `IntentAnswer` 时必须填充：
   - `source_type = "help_final"`
   - `source_ref_id = help_card_id`
   - `answer_title`
   - `answer_summary`
   - `confidence`
   - `success_count = 0`
   - `rejection_count = 0`
5. 不要只把长期记忆字段继续塞进 `evidence_json`。
6. 保留必要兼容字段可以，但标准查询必须能通过一等列完成。

## 禁止修改

- 不要改前端。
- 不要接真实 LLM。
- 不要接真实登录。
- 不要改推荐卡视觉。
- 不要删除或放宽本轮新增测试。
- 不要绕过 PipiFinalizeGraph。
- 不要把 `source_type/source_ref_id` 只写进 `evidence_json`。
- 不要删除现有 seed 数据来规避 migration。

## 通过标准

- `uv run pytest app/tests/test_p10_intent_answer_memory.py -q -rx` 通过。
- `uv run pytest app/tests/test_p9_api_response_contract.py -q -rx` 继续通过。
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
- `uv run alembic heads` 输出单一新的 head。
- `uv run alembic current` 输出当前已升级到新的 head。
