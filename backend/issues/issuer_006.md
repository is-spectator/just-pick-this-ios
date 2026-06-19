# issuer_006.md

## 失败结论

本轮未通过。

Iter Group 6 / `issuer_005` 已复验通过：

```bash
cd backend
uv run pytest app/tests/test_p5_update_help_card_flow.py -q -rx
```

结果：

```text
3 passed
```

进入 Iter Group 7：Layered retrieval 后，当前 chat retrieval 仍没有按设计记录分层 `retrieval_hit.source_type`。

## 失败测试

- `test_retrieval_hits_include_image_asset`
- `test_retrieval_hits_include_help_answer_when_available`
- `test_retrieval_hits_include_recommendation_card_when_available`

已通过：

- `test_retrieval_hits_include_intent_answer`

## 失败原因

### 1. 大同决策请求只记录了 `intent_answer`

测试输入：

```text
我现在在大同喜晋道，不知道吃什么，给我推荐一个。
```

当前本轮 chat `RetrievalRun` 下的 `RetrievalHit.source_type`：

```text
{"intent_answer"}
```

缺少：

```text
image_asset
```

虽然 payload 里带了 `image_asset_id`，但设计要求 retrieval 日志按层写，图片证据应作为单独 `source_type="image_asset"` 的 retrieval_hit。

### 2. 有 HelpAnswer 后，后续 chat retrieval 没有记录 `help_answer`

测试先创建韩国小众 help card，发布后提交 3 条 one-liner 并最终化，然后同一 conversation 再问：

```text
韩国逛街买什么，给我选一个。
```

当前本轮 chat `RetrievalHit.source_type`：

```text
{"intent_answer"}
```

缺少：

```text
help_answer
```

`PipiFinalizeGraph` 的 retriever 已经会记录 `help_answer`，但 chat-first retrieval 仍没有查询和记录历史 human evidence。

### 3. 有最终 RecommendationCard 后，后续 chat retrieval 没有记录 `recommendation_card`

同样在 help card 满 3 条并生成最终推荐卡后，后续相关 chat request 的 retrieval 仍只记录：

```text
{"intent_answer"}
```

缺少：

```text
recommendation_card
```

设计要求历史最终推荐卡也进入 layered retrieval，供后续相似请求复用。

### 4. `web_result` 未在本组强制测试

本组没有新增强制 `web_result` 测试，因为当前本地环境不应依赖真实 Tavily/外网调用。但设计仍要求 retrieval 至少支持并记录：

```text
web_result
```

如果 web provider disabled，可以后续用 deterministic stub 或 injected retriever 覆盖。

## 复现命令

```bash
cd backend
uv run pytest app/tests/test_p6_layered_retrieval.py -q -rx
```

完整测试：

```bash
cd backend
uv run pytest -q -rx
```

本轮实际结果：

```text
3 failed, 44 passed
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

1. Chat retrieval 必须按层记录 `retrieval_hit.source_type`，不能只把证据 ID 塞进 `intent_answer` hit 的 payload。
2. 大同决策请求至少应记录：
   - `intent_answer`
   - `image_asset`
3. 当已有相关 HelpAnswer 时，后续 chat retrieval 应记录：
   - `help_answer`
4. 当已有相关 RecommendationCard 时，后续 chat retrieval 应记录：
   - `recommendation_card`
5. `web_result` 后续仍需覆盖。V0 可以 deterministic，不要求真实 Tavily，但日志层必须能写 `source_type="web_result"`。
6. 这些 hit 必须落库到 `retrieval_hits`，并挂在本轮 chat `RetrievalRun` 上。

## 禁止修改

- 不要改前端。
- 不要接真实 LLM。
- 不要接真实登录。
- 不要改推荐卡视觉。
- 不要绕过 `PipiChatGraph`。
- 不要删除或放宽本轮新增测试。
- 不要只改 API response，不落库 `retrieval_hits`。
- 不要把所有证据继续压进 `intent_answer.payload_json`。

## 通过标准

- `uv run pytest app/tests/test_p6_layered_retrieval.py -q -rx` 通过。
- `uv run pytest app/tests/test_p5_update_help_card_flow.py -q -rx` 继续通过。
- `uv run pytest app/tests/test_p4_intent_taxonomy.py -q -rx` 继续通过。
- `uv run pytest app/tests/test_p3_finalize_tool_chain.py -q -rx` 继续通过。
- `uv run pytest app/tests/test_p2_finalize_graph_path.py -q -rx` 继续通过。
- `uv run pytest app/tests/test_p1_graph_checkpoint.py -q -rx` 继续通过。
- `uv run pytest app/tests/test_p0_smalltalk_state_flow.py -q -rx` 继续通过。
- `uv run pytest -q -rx` 通过。
- `uv run alembic heads` 输出单一 head：`0003_card_image_fk (head)`。
- `uv run alembic current` 输出当前版本：`0003_card_image_fk (head)`。
- 大同请求的 `retrieval_hits.source_type` 包含 `intent_answer` 和 `image_asset`。
- 有 HelpAnswer 后的相关请求包含 `help_answer`。
- 有 RecommendationCard 后的相关请求包含 `recommendation_card`。
