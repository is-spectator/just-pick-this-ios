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
2. `PipiChatGraph` retrieves knowledge before deciding a tool call.
3. Recommendation cards must be created through tools.
4. Help cards / “求一个” must be created and published through tools.
5. “来一句” is human evidence, not the final answer.
6. `PipiFinalizeGraph` produces the final recommendation card after enough help answers.
7. Persist conversation, turn, agent_run, tool_call, retrieval_run, retrieval_hit, intent_answer, recommendation_card, help_card, help_answer, and light_event.
8. Recommendation cards must bind a verified `image_asset` where `is_ai_generated=false`.
9. Database `intent_answers` are reference evidence, not final card copy.
10. Pipi may compose card copy with a deterministic adapter or an approved model provider, but the recommendation card must still be created through the tool path.

## Prohibited

- Do not make `/recommend` the main entry.
- Do not let a model directly emit final recommendation-card JSON without a tool call.
- Do not keep business state only in memory.
- Do not use AI-generated images.
- Do not let web search or an LLM invent image URLs for cards.
