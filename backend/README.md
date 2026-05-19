# 就选这个 Python Backend

Python 版“皮皮 Agent Runtime”。主入口是 chat，不是 `/recommend`。

## Stack

- Python 3.11+
- FastAPI
- LangGraph Python
- SQLAlchemy 2.0
- Alembic
- PostgreSQL
- Pydantic v2
- pytest
- uv

## Setup

```sh
cd backend
uv sync --extra dev
cp .env.example .env
```

编辑 `.env`：

```sh
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/just_pick_this_agent_v0
PIPI_CARD_COMPOSER=deterministic
```

本地如果使用 macOS 当前用户免密 PostgreSQL，也可以类似：

```sh
createdb just_pick_this_agent_v0
DATABASE_URL=postgresql+psycopg://fangnaoke@localhost:5432/just_pick_this_agent_v0
```

## Database

```sh
uv run alembic upgrade head
```

Seed 数据会在 service 首次启动时幂等写入：

- `datong-xijindao / knife-cut-noodles-meatball`
- `korea-seongsu / shopping-street`
- 两条 deterministic `intent_answers`

这些 `intent_answers` 只是皮皮加工推荐卡时的可信参考，不会被当作最终卡片文案原样吐给 App。

## Pipi card composition

默认离线模式：

```sh
PIPI_CARD_COMPOSER=deterministic
```

启用 DeepSeek 加工数据库参考答案：

```sh
PIPI_CARD_COMPOSER=deepseek
DEEPSEEK_API_KEY=...
DEEPSEEK_MODEL=deepseek-reasoner
```

可选网页证据入口：

```sh
WEB_SEARCH_PROVIDER=tavily
TAVILY_API_KEY=tvly-YOUR_API_KEY
TAVILY_SEARCH_MAX_RESULTS=5
TAVILY_IMAGE_MAX_RESULTS=8
TAVILY_TIMEOUT_SECONDS=8
```

Tavily 用途：

- 皮皮总结时可检索网页事实。
- 可通过 `include_images` 找真实网页引用图候选。
- 所有图片候选都会先写入 `image_assets`。
- 候选默认不是可展示图片，只有通过规则过滤后才会 `displayable=true`。

图片规则：

- 图片优先，但不是强制。
- 有可信引用图就挂卡。
- 无可信图就返回 `image=null`，不因此强制进入“求一个”。
- 模型不能编图片 URL。
- 不使用 AI 生成图。
- 可展示图片必须是 verified、displayable 且 `is_ai_generated=false` 的 `image_assets`。

## Run

```sh
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8788
```

## Health

```sh
curl http://127.0.0.1:8788/health
```

Expected:

```json
{"ok": true}
```

## API

- `POST /v1/bootstrap`
- `POST /v1/chat/turn`
- `GET /v1/help-feed`
- `POST /v1/help-cards/{id}/one-liner`
- `GET /v1/light-events`
- `GET /v1/cards/{id}`
- `POST /v1/cards/{id}/accept`

## Tests

```sh
uv run pytest
uv run ruff check app tests
```

The acceptance tests cover the chat-first loop: bootstrap, Datong Top 1, Korea help draft, publish, help feed, one-liner evidence, final card, intent answer, light event, retrieval records, and tool call records.

## Rules

- `/v1/chat/turn` is the product entry.
- Recommendation cards and help cards are tool calls.
- “来一句” is human evidence, not the final answer.
- Final answers are produced by `PipiFinalizeGraph`.
- All runtime state is persisted in PostgreSQL.
- `intent_answers` 是参考证据，不是最终答案；皮皮会按当前问题重新组织卡片文案。
- DeepSeek / web search 是可选加工层；生成卡片仍必须走 tool call。
- 不使用 AI 生成图片；模型不能编图片 URL。
- 图片不是强制字段；有图时只能来自 verified、displayable、非 AI 的 `image_assets`。
