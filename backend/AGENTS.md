# Backend Agent Rules

This backend is the Python “皮皮 Agent Runtime” for `就选这个`.

## Architecture

- Main product entry: `POST /v1/chat/turn`
- Framework: FastAPI
- Agent runtime: LangGraph Python
- Persistence: SQLAlchemy 2.0 + Alembic + PostgreSQL
- Schemas: Pydantic v2
- Tests: pytest
- Package runner: uv

## Runtime Rules

1. User input is persisted as a conversation turn before agent work.
2. `/v1/chat/turn` is the only product chat entry point.
3. `PipiChatGraph` is only the outer workflow/checkpoint wrapper.
4. `PipiLoop` is the only single-turn agent engine for tool-capable turns.
5. The main tool loop is `Reasoner -> AbilityCenter -> ToolResult -> Evaluator -> Reasoner -> Answer`.
6. A `Reasoner` may output only `tool` or `answer`.
7. A tool must be executed through the AbilityCenter boundary used by the chat path.
   For the current product path, that canonical implementation is
   `DbPipiAbilityCenter` in `app.services.chat`. The generic
   `app.ability.center.AbilityCenter` is the schema/permission wrapper and
   migration target, not the active DB persistence boundary for product turns.
   `DbToolExecutor` is an internal helper owned by `DbPipiAbilityCenter`; API
   routes, LangGraph nodes, and Reasoner code must not call it directly.
8. `ToolResult` must be appended to state and read by the next `Reasoner` iteration.
9. `AnswerDecision` is the normal successful loop exit; max-iteration and gate-failed exits must be safe answers that do not create cards.
10. Greeting, smalltalk, app-help, and unknown inputs do not enter the tool loop.
11. Recommendation cards must be created through tools.
12. Help cards / “求一个” must be created, updated, and published through tools.
13. “来一句” is human evidence, not the final answer.
14. `PipiFinalizeGraph` produces the final recommendation card after enough help answers.
15. Persist conversation, turn, agent_run, tool_call, retrieval_run, retrieval_hit, intent_answer, recommendation_card, help_card, help_answer, and light_event.
16. Recommendation cards must bind a verified, displayable `image_asset` where `is_ai_generated=false`; AMap place cards are the exception and must bind `place` plus `action` instead.
17. If there is no trusted image or AMap place, no evidence, or confidence is too low, create a help card instead of forcing a recommendation card.
18. Database `intent_answers` are reference evidence, not final card copy.
19. V0 uses the deterministic `Reasoner` / model adapter only; a real LLM must be introduced later by replacing `ModelAdapter`, not by bypassing the Harness.
20. The Hybrid Harness must persist/trace `input_gate_result`, `context_pack`, `reasoner_decision`, `tool_call`, `tool_result`, `evaluator_result`, and `answer_gate_result`.
21. Recommendation card UI may expose exactly one `decision_factor`; multi-reason card JSON is rejected by the evaluator.
22. Venue ordering requests such as “我在海底捞三里屯，点什么” route as `in_venue` + `ordering_bundle`, not as nearby area restaurant search.

## Prohibited

- Do not make `/recommend` the main entry.
- Do not let a model directly emit final recommendation-card JSON without a tool call.
- Do not keep business state only in memory.
- Do not use AI-generated images.
- Do not let web search or an LLM invent image URLs for cards.
- Do not enable a real model provider for V0.
