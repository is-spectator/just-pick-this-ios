# issuer_harness_unification.md

## 结论

当前后端已经有 `InputGate`、`ContextBuilder`、`PipiLoop`、`AbilityCenter`、`Evaluator`、`AnswerGate`、`TraceStore` 的雏形，但 `/v1/chat/turn` 主链路还没有收口到 Hybrid Harness。主路径仍然是旧 `PipiChatGraph` 内部的 `retrieve_knowledge -> evaluate_evidence -> decide_next_action -> execute_tool -> respond`，所以现在属于“两套 agent 机制并存”。

## 审计问题

1. `/v1/chat/turn` 当前实际调用链是什么？
   - `run_chat_turn` 先落 `Turn`，运行 `run_input_gate`，然后调用 `build_pipi_chat_graph().invoke(...)`。
   - 图内仍执行 `input_gate -> build_context -> rewrite_query -> classify_intent -> retrieve_knowledge -> evaluate_evidence -> decide_next_action -> execute_tool -> respond`。

2. 是否已经使用 PipiLoop？
   - 没有。主链路没有实例化或调用 `PipiLoop.run`。

3. PipiLoop 是否只是旁路？
   - 是。`PipiLoop` 目前只被单测覆盖，未成为 `/v1/chat/turn` 的执行引擎。

4. 是否存在 DeferredAbilityCenter 出现在主链路？
   - `PipiLoop` 默认仍会使用 `DeferredAbilityCenter`。主链路未调用 `PipiLoop`，所以生产 happy path 暂时没走它；但一旦直接 `build_pipi_loop()` 接入，会有旁路风险。

5. 当前 AbilityCenter 是否真实执行工具？
   - `AbilityCenter` 已实现 schema/permission/pre/postcondition，并有 registry wrapper；但主链路实际使用的是 `DbToolExecutor`，不是 `AbilityCenter`。

6. ToolResult 是否会回灌给 Reasoner？
   - 只在 `PipiLoop` 单测路径中回灌。主链路旧图只执行一次 `decide_next_action -> execute_tool -> respond`，没有 reasoner 看到真实 `ToolResult` 后再决定 answer。

7. PipiChatGraph 是否还在执行旧 retrieve / decide / execute / respond？
   - 是。旧节点仍是主路径。

8. InputGate 是否在主链路前置？
   - 部分是。`run_chat_turn` 和 `PipiChatGraph.input_gate` 都会运行 InputGate，但图内后续仍有旧业务节点。

9. 你好 / 哈哈 / 你是谁 是否会创建 Question？
   - 当前 `run_chat_turn` 会根据 InputGate 的 `should_create_question=false` 避免创建 Question；已有测试覆盖，但需要在最终主链路中继续保证。

10. loop_trace 是否包含完整 Harness 事件？
   - 不完整。当前图 trace 主要有 `input_gate_result`、`reasoner_decision`、`tool_result`、`answer`。
   - 缺少标准化 `context_pack`、独立 `tool_call`、`evaluator_result`、`answer_gate_result`。

11. RecommendationCard 是否仍支持多 reasons / bullets？
   - 旧模型和持久化模型仍保留 `bullets_json`，部分 payload 仍可能出现 `followups`；`AbilityCenter` 层的输入较干净，但不是唯一入口。

12. HelpCard 是否仍可能生成泛 title？
   - 生产路径已有 `_help_card_payload` 做了部分修正，但 eval/smoke 及旧工具中仍存在泛化风险，例如 generic wants/avoids。

13. Finalize 是否走 PipiFinalizeGraph，还是旁路函数？
   - `PipiFinalizeGraph` 存在，但 `DbToolExecutor._finalize_help_card` 仍直接调用 `finalize_help_card_now`，这是旁路风险。

14. 是否已有质量评分报告机制？
   - 目前只有 evaluator 单点质量门和若干测试，没有完整 `quality_report` / `case_quality_scores` 生成链路。

15. 是否已有 seed gap report / agent improvement report？
   - 有历史报告和测试文件，但没有统一由当前 benchmark runner 生成的稳定报告链路。

## 必须修复

1. `/v1/chat/turn` 主链路必须改为：
   `persist_turn -> InputGate -> ContextBuilder -> PipiLoop -> AbilityCenter -> Evaluator -> AnswerGate -> persist_response`。
2. `PipiChatGraph` 只能做外层 workflow/checkpoint，不再执行旧 retrieve/decide/execute/respond 业务链。
3. 主链路不得使用 `DeferredAbilityCenter`。
4. `ToolResult` 必须回灌给 Reasoner，且只有 `AnswerDecision` 才能结束 loop。
5. 完整 trace 必须包含：
   - `input_gate_result`
   - `context_pack`
   - `reasoner_decision`
   - `tool_call`
   - `tool_result`
   - `evaluator_result`
   - `answer_gate_result`
6. `Finalize` happy path 必须走 `PipiFinalizeGraph` / `PipiLoop`，不能直接调用 `finalize_help_card_now`。
7. Eval 报告需要补齐 quality scoring 和 report 输出。

## 禁止修改

- 不要改移动端。
- 不要接真实 LLM。
- 不要恢复普通 `/recommend` 主入口。
- 不要删除现有回归测试。
- 不要让模型直接吐推荐卡/求一个 JSON 绕过工具。

## 通过标准

- `uv run pytest -q -rx` 全绿。
- `你好` 不建 Question、不 retrieval、不 tool、不出卡。
- 大同喜晋道路径为 `search_knowledge -> create_recommendation_card -> answer`。
- 韩国小众路径为 `search_knowledge -> draft_help_card -> answer`。
- `PipiLoop` 是 `/v1/chat/turn` 的唯一单轮 agent engine。
- `PipiChatGraph` 只保留外层编排和 checkpoint wrapper。
- Admin/debug trace 可以回放完整 loop。
