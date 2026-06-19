# issuer_008.md

## 失败结论

本轮未通过。

Iter Group 8 / `issuer_007` 已复验通过：

```bash
cd backend
uv run pytest app/tests/test_p7_evidence_evaluator.py -q -rx
```

结果：

```text
3 passed
```

进入 Iter Group 9：Tool schema 对齐后，当前 recommendation card schema 和 help card schema 仍未满足设计。

## 失败测试

- `test_recommendation_card_schema_is_minimal`
- `test_help_card_schema_is_structured`

## 失败原因

### 1. RecommendationCard item / decision_factor 结构不足

设计目标：

```json
{
  "item": {
    "title": "...",
    "subtitle": "...",
    "category": "..."
  },
  "decision_factor": {
    "text": "...",
    "key": "..."
  },
  "image_asset_id": null,
  "evidence_ids": [],
  "retrieval_run_id": "..."
}
```

当前字段：

```text
RecommendationCardItem: {"title"}
RecommendationDecisionFactor: {"text"}
```

缺少：

```text
item.subtitle
item.category
decision_factor.key
```

当前 `CreateRecommendationCardInput` 已有 `retrieval_run_id`，但仍包含一等 legacy display 字段：

```text
warning
```

设计要求不要主推：

```text
reasons[]
bullets[]
followups[]
warning
```

这些只能作为兼容/内部字段，不能作为标准 tool input 的一等字段。

### 2. HelpCard schema 仍是 `context_text` 扁平结构

设计要求求助卡 tool 支持结构化字段：

```text
context
wants
avoids
constraints
revision
reward
answer_stats
```

当前 `DraftHelpCardInput` 字段：

```text
question_id
owner_user_id
title
context_text
min_answers_required
```

当前 `HelpCardOutput` 也仍是：

```text
help_card_id
question_id
owner_user_id
title
context_text
status
answer_count
min_answers_required
published_at
```

`UpdateHelpCardInput` 也仍以 `title/context_text/min_answers_required` 为核心，缺少结构化 update patch。

## 复现命令

```bash
cd backend
uv run pytest app/tests/test_p8_tool_schema_alignment.py -q -rx
```

完整测试：

```bash
cd backend
uv run pytest -q -rx
```

本轮实际结果：

```text
2 failed, 50 passed
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

1. `RecommendationCardItem` 必须支持：
   - `title`
   - `subtitle`
   - `category`
2. `RecommendationDecisionFactor` 必须支持：
   - `text`
   - `key`
3. `CreateRecommendationCardInput` 必须保留：
   - `item`
   - `decision_factor`
   - `image_asset_id`
   - `evidence_ids`
   - `retrieval_run_id`
4. `CreateRecommendationCardInput` 不应再把下列 legacy display 字段作为一等标准字段：
   - `reasons`
   - `reason`
   - `bullets`
   - `followups`
   - `warning`
5. `DraftHelpCardInput`、`HelpCardOutput` 必须支持结构化字段：
   - `context`
   - `wants`
   - `avoids`
   - `constraints`
   - `revision`
   - `reward`
   - `answer_stats`
6. `UpdateHelpCardInput` 必须能更新结构化字段：
   - `context`
   - `wants`
   - `avoids`
   - `constraints`
   - `revision`
   - `reward`
7. `context_text` 可以作为兼容输出或内部 DB 字段，但不能继续作为标准 tool schema 的唯一核心结构。

## 禁止修改

- 不要改前端。
- 不要接真实 LLM。
- 不要接真实登录。
- 不要改推荐卡视觉。
- 不要绕过 tool/function call。
- 不要删除或放宽本轮新增测试。
- 不要把结构化字段塞进一个无类型 `metadata` 字段来规避 schema。
- 不要继续把 `warning` 作为 `create_recommendation_card` 的标准一等输入。

## 通过标准

- `uv run pytest app/tests/test_p8_tool_schema_alignment.py -q -rx` 通过。
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
- 推荐卡 tool schema 收敛到 item / decision_factor / image / evidence / retrieval_run。
- 求助卡 tool schema 支持 context / wants / avoids / constraints / revision / reward / answer_stats。
