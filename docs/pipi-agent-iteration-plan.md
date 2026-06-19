# 皮皮 Agent Runtime 迭代计划

## 北极星目标

在 4 个迭代内，把皮皮从“可运行的 deterministic Agent 后端”推进到“可稳定测试、可观测、可灰度接入 LLM、可持续自进化的 Hybrid Agent Runtime”。

最终验收目标：

- 100-case eval pass rate >= 95%，且 chitchat / clarification / help_card_draft / recommendation_card 四类均无系统性误路由。
- 500-case eval quality overall >= 0.82，P0 路由错误为 0。
- `/v1/chat/turn` P95 latency <= 6s，P50 <= 3.5s。
- 所有 product 请求都有可回放 trace，包含 InputGate、ContextBuilder、PipiLoop、AbilityCenter、Evaluator、AnswerGate。
- LLM 先以 shadow mode 接入，连续 3 轮 benchmark schema-valid rate >= 98% 后，才允许小流量参与 reasoner。
- 推荐卡不再输出泛 decision_factor；求助卡不再输出“北京这顿饭，求一个”类泛卡。

## 当前优化方向拆解

### 1. 路由质量

问题：

- 用户闲聊、信息不足、真实决策请求、店内点菜、求助更新容易混在一起。
- 如果 InputGate 或 query rewrite 不够稳，后面再强的 tool 都会走错。

目标：

- 让 InputGate 成为产品链路的第一道硬闸门。
- 明确四种结果：直接回答、追问、推荐卡、求助卡。
- 求助卡不能作为默认兜底，只能在“上下文足够但没有答案”时生成。

任务：

1. 补齐 `InputGateResult` 的可解释字段：`intent_type`、`missing_slots`、`location_state`、`decision_domain`、`confidence`、`allowed_tools`、`reason`。
2. 增加 query rewrite 前置层，输出 `canonical_query` 和 `extracted_slots`，但不直接决定工具。
3. 建立路由优先级：chitchat > clarification > venue_ordering > area_food > help_update > publish > help_card_draft。
4. 对“广东人 / 清淡 / 不辣 / 两个人 / 在望京 SOHO”等隐性约束做 slot extraction。
5. 将“帮我找一下北京市朝阳区最好吃的热干面”路由为 area_food，而不是 fallback error。
6. 明确 unknown 的安全策略：默认追问，不创建求助卡。

验收：

- `你好`、`你是谁`、`谢谢`：0 Question、0 RetrievalRun、0 ToolCall。
- `我想吃饭`、`帮我选一家`、`附近有什么好吃的`：response_kind=clarification。
- `我在三里屯海底捞，两个人不太能吃辣，帮我点`：in_venue + ordering_bundle。
- 路由错误进入 `quality_report` 的 `wrong_target_type` / `wrong_location_priority` 标签。

### 2. 证据质量

问题：

- 当前有时能拿到 POI，但证据不足仍硬推。
- 有时推荐理由太空，比如“适合现在直接做决定”。
- 地图 POI 不能等同于“好吃证据”。

目标：

- 把“能找到地点”和“值得推荐”分开。
- 推荐卡必须有 evidence chain；没有证据则追问或求助。

任务：

1. 将 evidence 分层：local_seed、intent_answer、human_answer、amap_poi、web_result、image_asset。
2. 建立 `EvidenceEvaluator` 输出：`can_recommend`、`confidence`、`missing_requirements`、`reason`。
3. 对 area_food 推荐设置最低证据要求：地点存在 + 需求匹配 + 至少一个推荐依据。
4. 对 ordering_bundle 推荐设置最低证据要求：venue 命中 + ordering seed / approved answer。
5. POI 推荐卡的 decision_factor 必须引用距离、口味、约束之一，不能只说“稳”。
6. 图片只做展示增强，不作为推荐依据；无 verified 图片时 image=null。

验收：

- 每张推荐卡都有 `provenance.evidence_ids`。
- `decision_factor.text` 不允许只有“稳”“不折腾”“适合现在决定”这类空话。
- 地图 POI 无口味证据时，不能自动声称“最好吃”。
- 低证据 case 在 trace 中能看到 `missing_requirements`。

### 3. LLM 接入策略

问题：

- 直接让 LLM 控制工具会放大误路由。
- 但不用 LLM，复杂表达理解能力不足。

目标：

- LLM 先只进入 shadow mode，做 query rewrite、intent compare、decision suggestion。
- 产品输出仍由 deterministic path 决定。

任务：

1. `ModelAdapter` 支持 OpenAI provider，但默认 disabled。
2. `ShadowReasoner` 每轮记录 deterministic decision 和 LLM decision。
3. LLM 输出必须通过 `ReasonerDecision` schema validation。
4. schema_error、timeout、provider_error 都只写 trace，不影响用户响应。
5. Admin Trace 展示 deterministic vs shadow diff。
6. Benchmark 产出 shadow comparison report。
7. 连续稳定后，选择低风险能力灰度：query rewrite，而不是 tool execution。

验收：

- shadow 开启后 product output 不变。
- shadow 不调用 AbilityCenter，不写卡，不写 HelpCard。
- shadow schema-valid rate >= 98% 才能进入下一阶段。
- LLM timeout 不导致 `/v1/chat/turn` 失败。

### 4. 工具面收窄

问题：

- 工具多时，模型容易选错。
- 推荐卡和求助卡 schema 一旦膨胀，前端和评测都会不稳定。

目标：

- AbilityCenter 成为唯一工具入口。
- 工具 schema 越窄越好，业务表达放在输入槽位和 evidence，不放在自由 JSON。

任务：

1. 保持 `create_recommendation_card` 只接收 item、decision_factor、image_asset_id、evidence_ids、retrieval_run_id。
2. `draft_help_card` 强制结构化 context、wants、avoids、constraints。
3. `update_help_card` 只能更新同一张卡。
4. `publish_help_card` 只能处理 active draft。
5. `submit_one_liner_answer` 只写 human evidence，不触发直接最终推荐。
6. 将 legacy `reasons[]`、`bullets[]`、`followups[]` 标记 deprecated，默认 API 不返回。

验收：

- RecommendationCard v2 API 不返回 legacy 字段。
- 多 decision_factor 在 Evaluator 直接失败。
- ToolCall 全部可在 Admin Trace 中追踪。

### 5. 自进化闭环

问题：

- 当前修复主要靠人工看截图和报告。
- 需要把“失败 case -> 归因 -> seed gap / prompt gap / route gap / data gap -> 修复计划”自动化。

目标：

- 每次 benchmark 自动生成可执行改进报告。
- 系统能区分：缺数据、路由错、证据弱、文案差、工具契约错。

任务：

1. `quality_report` 保留总体分和维度分。
2. `seed_gap_report` 只记录“期望推荐但没有可用答案”的 case。
3. `pipi_agent_improvement_report` 记录路由、工具、证据、文案、性能问题。
4. `low_quality_cases.md` 按 P0/P1/P2 分组。
5. 每个失败 case 必须能链接到 trace_id / agent_run_id。
6. 将修复建议转化为 issue 模板：问题、证据、复现、修复范围、禁止修改、验收测试。

验收：

- 每次 benchmark 后报告文件稳定生成。
- 每个 P0 失败都有明确 owner：router / evidence / tool / card_contract / data_seed。
- 不允许把 wrong recommendation 误归因成 seed gap。

## 迭代排期

### Iteration 1：路由与追问收口

周期：2-3 天。

范围：

- InputGate 加 slot extraction。
- query rewrite 前置但不控制工具。
- clarification 替代默认 help_card fallback。
- 修复用户当前看到的“处理失败 / 泛求助卡 / 不会追问”问题。

交付：

- `test_input_gate_slot_extraction.py`
- `test_clarification_not_help_card.py`
- `test_area_food_hot_dry_noodle.py`
- benchmark 100-case pass rate >= 90%。

风险：

- 如果追问太多，会降低推荐卡命中率。
- 解决方式：只对 missing critical slots 追问，已具备 city+area+cuisine 时继续推荐。

### Iteration 2：证据评估与推荐质量

周期：3-4 天。

范围：

- EvidenceEvaluator 一等节点。
- decision_factor quality gate。
- area_food POI + evidence 分离。
- 求助卡泛化拦截。

交付：

- `test_evidence_evaluator_quality_gate.py`
- `test_decision_factor_not_generic.py`
- `test_help_card_quality_gate.py`
- 500-case quality overall >= 0.76。

风险：

- 证据门槛过高会让求助卡变多。
- 解决方式：先标记 degraded，不直接 block；高风险场景才 block。

### Iteration 3：LLM Shadow Mode 实跑

周期：2-3 天。

范围：

- OpenAI ModelAdapter shadow。
- query rewrite shadow output。
- deterministic vs LLM diff report。
- Admin Trace 展示 shadow。

交付：

- `shadow_comparison_report.md`
- schema-valid rate >= 98%。
- timeout/error 不影响 product。

风险：

- LLM 输出不稳定。
- 解决方式：只收 JSON schema，失败直接丢弃。

### Iteration 4：灰度 LLM Query Rewrite

周期：3-5 天。

范围：

- 只允许 LLM 参与 query rewrite，不允许直接选 tool。
- deterministic InputGate 仍有最终裁决权。
- 增加 feature flag：`LLM_REWRITE_ENABLED`。

交付：

- 对复杂表达的 slot extraction 提升。
- 500-case quality overall >= 0.82。
- P95 latency <= 6s。

风险：

- LLM rewrite 可能改变用户意图。
- 解决方式：保留 original_query、canonical_query、rewrite_confidence，低置信不用。

### Iteration 5：自进化报告自动转 issue

周期：2-3 天。

范围：

- benchmark report -> issue markdown。
- 按 P0/P1/P2 输出修复建议。
- 支持 seed gap 和 agent improvement 分离。

交付：

- `backend/issues/generated/issuer_*.md`
- 每个 issue 自带测试建议和禁止修改范围。

风险：

- 自动报告噪声过多。
- 解决方式：只自动生成 P0/P1，P2 聚合。

## 优先级矩阵

| 优先级 | 主题 | 为什么先做 | 验收信号 |
| --- | --- | --- | --- |
| P0 | 路由与追问 | 决定是否出卡，错了后面全错 | chitchat/clarification/venue_order 无系统性误判 |
| P0 | 证据质量 | 防止恶心人的空推荐 | decision_factor 有证据、有约束、有场景 |
| P1 | LLM Shadow | 为接真实 LLM 做安全缓冲 | product output 不变，shadow 可对比 |
| P1 | 工具契约 | 保证前端、eval、后台稳定 | v2 card schema 稳定 |
| P2 | 自进化 issue | 提高后续修复效率 | benchmark 自动产出可执行 issue |

## 不做事项

- 不直接让 LLM 调 tool。
- 不让 LLM 直接创建卡片 JSON。
- 不改 iOS UI。
- 不新增普通 `/recommend`。
- 不用 smoke benchmark 糊弄 product path。
- 不把 POI 搜索当成“好吃证据”。

## 每轮固定验收命令

```bash
cd backend
uv run pytest -q -rx
uv run alembic heads
uv run alembic current
uv run ruff check app tests
```

如果 eval-lab 可用：

```bash
cd /Users/fangnaoke/Documents/code/pipi-eval-lab
uv run python scripts/run_benchmark.py \
  --suite benchmarks/pipi_system_ground_truth_100_v1.yaml \
  --min-pass-rate 0.9
```

## 最终判断

这条路线成功，不是看“接了几个工具”，而是看三件事：

1. 皮皮知道什么时候不该出卡。
2. 皮皮出卡时有真实证据和具体理由。
3. 每次错误都能通过 trace 和 benchmark 自动归因到下一轮修复。
