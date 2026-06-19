# 皮皮 Prompt 优化文档

更新时间：2026-06-08

## 结论

不是所有 `/ops/prompts` 里的条目都是“LLM 正在逐字消费的 prompt”。

当前分三类：

| 类型 | Prompt | 真实性 | 当前是否直接影响运行时 |
| --- | --- | --- | --- |
| LLM 逐字 prompt | `reasoner.system` | 来自 `OpenAIReasoner._openai_reasoner_messages` | 仅 `PIPI_MODEL_PROVIDER=openai` 时影响 |
| LLM 逐字 prompt | `shadow_reasoner.system` | 来自 `ShadowReasoner._openai_shadow_messages` | 仅 shadow LLM 开启时影响 |
| Deterministic 规则文档 | `input_gate.system` / `context_builder.policy` / `reasoner.tool_policy` / `evaluator.system` / `answer_gate.system` / `help_card_extractor.system` / `finalizer.system` | 当前代码规则的文本化版本 | 现在不直接驱动代码，主要用于运营理解和后续接入 |
| 真正热更新策略 | `area_food_evidence_policy` | 来自 `agent_prompt_configs` / 默认配置 | 当前 deterministic product path 会读取 |

所以你要优化时，优先看：

1. `area_food_evidence_policy`：当前已经真实影响区域选店策略，是本阶段最优先的 prompt/policy 优化项。
2. `reasoner.system`：仅在 `PIPI_MODEL_PROVIDER=openai` 时逐字影响 product reasoner。
3. `shadow_reasoner.system`：用于影子评估和 diff。
4. 其他 deterministic prompt：先作为产品规则文档优化，后续再接入运行时。

Ops Prompt Center 当前状态：

- `area_food_evidence_policy` 已通过 `AgentPromptConfig` 支持后台热更新，并在 area food product path 运行时读取。
- `reasoner.system` / `shadow_reasoner.system` 有后台模板与版本管理，但实际运行时仍以代码里的 OpenAI prompt builder 为准；后续需要把模板渲染接进 ModelAdapter。
- `help_card_extractor.system` / `evaluator.system` 当前是 deterministic 规则文档，真实行为由 Python 规则实现。

## 运行时输入

`reasoner.system` 的 user payload 当前包含：

```json
{
  "user_message": "用户原话",
  "intent": "InputGate 判定意图",
  "allowed_tools": ["允许调用的工具"],
  "context_pack": "裁剪后的上下文包",
  "tool_results": "已有工具结果",
  "baseline_contract_decision": "deterministic baseline 决策"
}
```

`shadow_reasoner.system` 的 user payload 当前包含：

```json
{
  "context_pack": "裁剪后的上下文包",
  "deterministic_decision": "线上 deterministic 决策"
}
```

## Prompt 1：reasoner.system

状态：LLM 逐字 prompt。

源码位置：`backend/app/agent/reasoner.py` 的 `_openai_reasoner_messages`。

当前内容：

```text
你是皮皮 Agent 的 product reasoner，必须在 Harness 约束内工作。
你每轮只能输出一个 JSON object，且只能是二选一：
1. {"type":"tool","tool_name":"<allowed tool>","tool_args":{},"reason":"..."}
2. {"type":"answer","message":"...","ui_events":[],"data":{}}

硬规则：
1. 不能绕过 tool/function call，不能直接吐推荐卡 JSON 或求一个 JSON。
2. tool_name 必须来自 allowed_tools，不允许自造工具。
3. greeting / smalltalk / app_help 不能调用工具，只能 answer。
4. decision_request / help_request 首轮必须先 search_knowledge，不能跳过检索直接出卡。
5. search_knowledge 后如果证据不足、无 evidence_ids、无 approved answer，必须 draft_help_card。
6. create_recommendation_card / draft_help_card 等 card tool_result 返回后，下一轮必须 answer 收口。
7. 已有 card/help_card 工具结果时，answer 只能引用 tool_result 的 ui_events 和 data，不能编造新卡。
```

优化方向：

- 保留二选一 JSON 输出合同。
- 强化“不绕过 tool / AbilityCenter / Evaluator / AnswerGate”。
- 明确什么时候必须先 `search_knowledge`。
- 明确证据不足时必须 `draft_help_card`，不要硬推卡。
- 不要让模型直接输出推荐卡 JSON。

## Prompt 2：shadow_reasoner.system

状态：LLM 逐字 prompt。

源码位置：`backend/app/agent/shadow_reasoner.py` 的 `_openai_shadow_messages`。

当前内容：

```text
你是皮皮 Agent 的 shadow reasoner。你只做影子判断，不执行工具，不创建卡片，不影响线上答案。必须只输出符合 ReasonerDecision schema 的 JSON object。
推荐卡和求一个只能通过 tool_name 表达，不要直接输出卡片 JSON。
这是 audit-only：不能调用 AbilityCenter，不能写 RecommendationCard/HelpCard，不能改变 product output。
请在 reason 或 message 中覆盖 why_different_from_deterministic、risk_if_promoted、confidence 三点；不要新增 schema 外字段。
```

优化方向：

- 让 shadow 输出更利于和 deterministic 决策对比。
- 保持 audit-only，不能引导它执行副作用。
- 可以增加“解释为什么和 deterministic 不同”的 reason 质量要求。

## Prompt 3：area_food_evidence_policy

状态：当前真实热更新策略，不在 `/ops` 新 Prompt Center 体系里，但已经被运行时消费。

源码位置：

- 默认配置：`backend/app/services/prompt_config.py`
- 消费位置：`backend/app/services/chat.py`，`get_prompt_config(session, "area_food_evidence_policy")`

当前内容：

```text
先尊重用户显式偏好和身份线索，再考虑距离。用户说广东人/粤/广州/深圳时，不要把湘菜、川菜、重辣火锅当作默认答案；优先搜索粤菜、广式、潮汕、茶餐厅、顺德。
```

当前配置：

```json
{
  "generic_food_keyword": "餐饮",
  "profile_cuisine_rules": [
    {
      "name": "cantonese_profile",
      "when_any": ["广东人", "广州人", "深圳人", "粤", "广东口味"],
      "search_keyword": "粤菜",
      "display_food": "粤菜",
      "decision_prefix": "你说自己是广东人，先按粤菜/清淡口味筛一遍。",
      "prefer_terms": ["粤", "广东", "广州", "潮汕", "茶餐厅", "广式", "顺德", "港式"],
      "reject_terms": ["长沙", "湘菜", "川菜", "麻辣", "重辣", "火锅"],
      "require_preferred_match": true
    },
    {
      "name": "non_spicy_profile",
      "when_any": ["不吃辣", "不能吃辣", "不太能吃辣", "少辣", "不要辣"],
      "search_keyword": "清淡餐厅",
      "display_food": "清淡口味",
      "decision_prefix": "你说不太能吃辣，先避开重辣和红油火锅。",
      "prefer_terms": ["清淡", "粤", "杭帮", "本帮", "淮扬", "潮汕", "茶餐厅", "汤", "蒸"],
      "reject_terms": ["重辣", "麻辣", "辣锅", "红油", "川菜", "湘菜", "火锅", "烧烤"],
      "require_preferred_match": true
    }
  ]
}
```

优化方向：

- 已新增 profile：`jiangzhe_profile`、`sichuan_profile`、`dongbei_profile`、`vegetarian_profile`、`parents_profile`、`date_profile`、`solo_profile`、`non_spicy_profile`。
- 每条规则必须有 `name`、`when_any`、`search_keyword`、`display_food`、`decision_prefix`、`prefer_terms`、`reject_terms`、`require_preferred_match`。
- `require_preferred_match=true` 会更保守，可能导致证据不足转求一个。

## Prompt 4：input_gate.system

状态：deterministic 规则文档，不是 LLM 逐字 prompt。

对应代码：`backend/app/harness/input_gate.py`。

当前内容：

```text
当前 V0 InputGate 是 deterministic gate，不调用 LLM。

执行规则：
1. 先 rewrite_query，抽取 canonical_query、slots、location_state、decision_domain。
2. greeting / smalltalk / app_help / unknown 不进入 PipiLoop，不创建 question，不检索，不开放 tools。
3. 含明确场景的 decision_request / help_request 才进入 loop。
4. venue_ordering 优先级高于 area_food；已在店内点菜时允许 search_knowledge、create_recommendation_card、draft_help_card。
5. area + food/cuisine 足够进入检索；模糊缺槽先文本澄清，不调用工具。
6. active help card 场景下，update_help_card / publish_help / one_liner_answer / finalize_request 走对应工具。
7. allowed_tools 是 Reasoner 的硬边界；后续 AbilityCenter 还会二次校验。
```

优化方向：

- 优化意图分类边界。
- 明确什么时候澄清，什么时候进入 loop。
- 尽量避免把“附近找餐厅”和“店内点菜”混淆。

## Prompt 5：context_builder.policy

状态：deterministic 规则文档，不是 LLM 逐字 prompt。

对应代码：`backend/app/services/chat.py` 的 context provider 和 graph metadata。

当前内容：

```text
当前 V0 ContextBuilder 是 deterministic context pack，不调用 LLM。

上下文包包含：
1. 当前 conversation_id、turn_id、user_message。
2. 最近对话 turns，保留用户历史决策上下文。
3. active_help_card，如果存在则作为求一个更新/发布/来一句/收口的上下文。
4. query_rewrite 结果和 latest_user_context。
5. client_context，例如位置、benchmark_case_id。
6. 工具输出会在 PipiLoop 中持续写入 context_pack.tool_outputs。

约束：
- 不补造事实。
- 只把已落库或当前 turn 可证明的信息放进 context。
- contextual follow-up 会拼接最近的决策上下文，但不替用户新增偏好。
```

优化方向：

- 定义哪些历史上下文要保留。
- 定义 active help card 如何影响当前 turn。
- 避免把旧偏好误带到新问题里。

## Prompt 6：reasoner.tool_policy

状态：deterministic 规则文档，不是 LLM 逐字 prompt。

对应代码：`backend/app/agent/reasoner.py` 的 `DeterministicReasoner.next`。

当前内容：

```text
当前 V0 Reasoner/Ability policy：

1. 如果上一个工具不是 search_knowledge，先收口 answer。
2. 如果 InputGate 不允许进入 loop，直接用 direct_answer_for_gate。
3. publish_help -> publish_help_card。
4. update_help_card -> update_help_card。
5. one_liner_answer -> submit_one_liner_answer；来一句只是 human evidence。
6. finalize_request -> finalize_help_card。
7. decision_request / help_request 首轮必须先 search_knowledge。
8. 检索后如果命中 is_card_ready_hit，才 create_recommendation_card。
9. 否则 draft_help_card，不硬推卡。
10. create_recommendation_card 参数来自 strongest evidence，必须带 evidence_ids、retrieval_run_id、confidence。
```

优化方向：

- 定义工具优先级。
- 定义何时从 search 转 card，何时转 help card。
- 强化“来一句只是 human evidence”。

## Prompt 7：evaluator.system

状态：deterministic 规则文档，不是 LLM 逐字 prompt。

对应代码：

- `backend/app/harness/evaluator.py`
- `backend/app/harness/evidence_evaluator.py`

当前内容：

```text
当前 V0 Evaluator 是 deterministic evaluator，不调用 LLM。

推荐卡检查：
1. 必须是单卡，不能返回多个 item。
2. decision_factor 必须具体，不能只有“稳/靠谱/不踩雷”等泛化描述。
3. 不允许旧字段 reasons / bullets / followups / why_questions / not_for / warning 泄漏到推荐卡合同。
4. venue ordering 要保留店内语境，避免把海底捞店内点菜误判成附近找餐厅。

证据检查：
1. hit score >= 0.7。
2. 必须有 answer_evidence 或合格 place evidence。
3. 图片可选；无图时仍可推荐，但必须有 evidence_ids。
4. 有图时必须 verified/displayable 且 is_ai_generated=false。
5. AMap/POI 只能作为 place evidence，必须有与用户偏好/路线/口味绑定的 decision_factor。
6. human_help_required 时不能硬推卡。
```

优化方向：

- 优化 evidence threshold。
- 优化 decision_factor 的“具体”定义。
- 明确图片不是推荐卡必需项；无图必须依赖 evidence_ids，不能因为缺图直接拒绝。

## Prompt 8：answer_gate.system

状态：deterministic 规则文档，不是 LLM 逐字 prompt。

对应代码：`backend/app/harness/answer_gate.py`。

当前内容：

```text
当前 V0 AnswerGate 是 deterministic guard，不调用 LLM。

禁止：
1. 在 assistant text 里直接输出推荐卡 JSON 或求一个 JSON。
2. 输出未通过 tool 落库的 card/help_card/light_event。
3. 输出 show_recommendation_card / show_help_card_draft 等 UI event 文案。
4. 泄漏 debug、trace、runtime、fallback、schema、provider、model 等内部词。
5. 声称“我已经生成/弹出/展示卡片”，除非对应 persisted id 来自 tool。

允许：
- 普通文本回答。
- 对已由工具落库的卡片/help_card/light_event 做安全收口。
```

优化方向：

- 强化不能泄漏内部链路。
- 保证用户看到的是自然语言，不是工具/后台文案。
- 明确什么时候可以引用已落库卡片。

## Prompt 9：help_card_extractor.system

状态：deterministic 规则文档，不是 LLM 逐字 prompt。

对应代码：`backend/app/agent/reasoner.py` 的 `_draft_help_args`。

当前内容：

```text
当前 V0 Help Card draft 由 deterministic Reasoner 生成参数。

规则：
1. 这是问题压缩器，不是用户原话截断器。
2. 必须抽 title、context、wants、avoids、constraints、missing_info。
3. title 必须具体，不能是“北京这顿饭，求一个”或“这顿饭，求一个”。
4. context 要保留 area / venue / city / scene / party_size / spicy_preference 等已知槽位。
5. wants 不允许只写“好吃”“别让我查”等泛词。
6. avoids 不允许写“多个选项”等产品规则，只保留用户真实避开项。
7. constraints.missing_info 标出缺失槽位，方便追问或求助收口。
8. 求一个用于证据不足、低置信、无 approved answer 场景；不是最终答案。
```

优化方向：

- 继续扩大 area / venue / party_size / taste_preference 的 deterministic 抽取覆盖。
- 让求一个标题更像用户会发出去的问题，但不能编造最终答案。
- 避免把最终答案写进 help card。

## Prompt 10：finalizer.system

状态：deterministic 规则文档，不是 LLM 逐字 prompt。

对应代码：`backend/app/agent/pipi_finalize_graph.py`。

当前内容：

```text
当前 V0 PipiFinalizeGraph 是 deterministic finalize graph，不调用 LLM。

执行顺序：
1. load_help_card。
2. load_help_answers。
3. retrieve_knowledge。
4. decide_final_answer。
5. finalize_help_card。
6. create_recommendation_card。
7. save_intent_answer。
8. light_user。

规则：
- help_answers 数量低于 min_answers_required 时，状态是 needs_more_answers。
- 最终推荐只基于 human evidence 和 retrieval hits。
- finalize_help_card 是 orchestration tool call，不直接伪造推荐卡。
- create_recommendation_card 必须通过 tool boundary。
- save_intent_answer 沉淀可复用人类证据。
- light_user 只在 final recommendation ready 后触发。
```

优化方向：

- 定义 human evidence 如何汇总为最终推荐。
- 定义低质量回答是否能参与 finalization。
- 定义最终卡的 confidence 与 light_user 触发阈值。

## 优化注意事项

1. 不能把推荐卡 JSON 直接写进 prompt，让模型吐出来。
2. 不能让 prompt 绕过 tool/function call。
3. `allowed_tools` 必须是硬边界。
4. 没有证据、没图、低置信时，应走 `draft_help_card`。
5. 来一句只能作为 human evidence，不是最终答案。
6. 当前要真实影响 deterministic 路径，优先改 `area_food_evidence_policy`。
7. 要让 `/ops` 里其他 prompt 真实热更新，需要后续把 `PromptRegistry.get_prompt(...)` 接进对应 runtime 节点。
