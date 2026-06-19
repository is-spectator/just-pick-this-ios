# Iteration 2 Evidence Quality Report

## 结论

本轮完成 `docs/pipi-agent-iteration-plan.md` 中的 Iteration 2：证据评估与推荐质量收口。

核心改动是把“是否可以出推荐卡”的判断从松散的 `has_answer_evidence + image/place`，收口到共享 evidence evaluator：

- AMap/POI 只算地点证据，不再天然等同于口味/推荐证据。
- 地点卡必须带有合格的 decision factor，并能锚定食物、偏好、路线或场景。
- 泛 decision factor 会被 evaluator 拒绝。
- 泛 help card 会被 evaluator 拒绝。
- retrieval hit payload 开始记录 `evidence_layers`，便于 trace 和后续 eval 归因。

## 已完成

- 新增 `app.harness.evidence_evaluator`
  - `evaluate_retrieval_hits`
  - `is_card_ready_hit`
  - `missing_requirements_for_hit`
  - `evidence_layers_for_payload`
  - `is_generic_decision_factor`

- PipiLoop reasoner 改用共享 `is_card_ready_hit`
  - 避免 POI-only 或泛理由误触发推荐卡。

- PipiChatGraph evidence trace 改用共享 `evaluate_retrieval_hits`
  - trace 中 `evidence_evaluation` 与 product reasoner 的证据判断保持一致。

- RecommendationCard evaluator 增加 `decision_factor_too_weak`
  - 拦截“适合现在直接做决定”“这一个证据最稳”等泛理由。

- Retrieval payload 增加 evidence layers
  - `intent_answer`
  - `image_asset`
  - `amap_poi`
  - `route`
  - `taste_or_preference`
  - `web_result`
  - `human_answer`
  - `recommendation_card`

## 新增测试

- `app/tests/test_evidence_evaluator_quality_gate.py`
  - POI-only + 泛 decision factor 不允许出卡。
  - POI + route + food decision factor 可以出卡。
  - Web reference 缺 answer/image 时保留旧 missing requirements。

- `app/tests/test_decision_factor_not_generic.py`
  - 泛 decision factor 被拒。
  - 具体区域/食物/路线 decision factor 通过。

- `app/tests/test_help_card_quality_gate.py`
  - 泛 help card 被拒。
  - 保留 area + food context 的结构化 help card 通过。

## 测试结果

```bash
cd backend
uv run pytest -q -rx
uv run alembic heads
uv run alembic current
uv run ruff check app tests
```

结果：

- pytest：通过
- alembic heads：`0007_agent_prompt_configs (head)`
- alembic current：`0007_agent_prompt_configs (head)`
- ruff：通过

## 未完成事项

- 本轮没有接入真实 LLM。
- 本轮没有实现 EvidenceEvaluator 的独立 LangGraph 节点，因为当前 product path 是 PipiLoop；先用共享 evaluator 保证 graph trace 和 reasoner 一致。
- 远程 100-case benchmark 未在本地运行；本轮完成 backend 单元与集成回归。

## 下一步建议

- Iteration 3 可以把 evidence evaluator 输出写入 benchmark quality report 的单 case 明细。
- 对 AMap place card 增加更细的 rerank 策略：距离只做 tie-breaker，口味/场景证据优先。
- 对 help card 生成 tool 加 precondition，直接阻止泛 title/context/wants 写库。
