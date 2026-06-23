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

## Hybrid Harness Architecture

The product chat path is:

```text
POST /v1/chat/turn
-> persist user Turn
-> InputGate
-> direct answer when should_enter_loop=false
-> ContextBuilder
-> PipiLoop
   -> Reasoner
   -> AbilityCenter
   -> ToolResult
   -> Evaluator
   -> Reasoner
   -> Answer
-> AnswerGate
-> persist assistant Turn / AgentRun output
-> return ui_events + metadata.loop
```

`PipiChatGraph` is the LangGraph outer wrapper for workflow state and
`thread_id=conversation_id` checkpointing. It must not be the business
retrieve/decide/execute engine. `PipiLoop` is the single-turn agent engine for
tool-capable turns, and the deterministic V0 reasoner can only produce `tool`
or `answer`. Tool outputs are appended back into `PipiState.tool_results` before
the next reasoner call.

Non-task inputs such as greeting, smalltalk, app-help, and unknown turns stop at
`InputGate` and return a direct answer without creating Question, RetrievalRun,
ToolCall, recommendation card, or help card.

Recommendation cards and help cards must come from tools. The user-facing
recommendation contract exposes one `decision_factor`; legacy multi-reason
fields are rejected by the evaluator/answer gate.

## Setup

```sh
cd backend
uv sync --extra dev
cp .env.example .env
docker compose up -d postgres
```

开发和测试使用 `uv sync --extra dev` 安装 pytest/ruff 等工具。生产启动脚本不使用 dev extra；部署环境应先安装运行依赖，然后用 `scripts/start_prod.sh` 启动。

如果使用随仓库的 Docker PostgreSQL，编辑 `.env`：

```sh
DATABASE_URL=postgresql+psycopg://just_pick_this:just_pick_this@localhost:5432/just_pick_this_agent_v0
PIPI_MODEL_PROVIDER=deterministic
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

Local test commands are split by database need:

```sh
./scripts/test_security_gate.sh   # no Docker and no DATABASE_URL required
./scripts/test_unit.sh            # no DB integration tests
uv run --extra dev pytest -q -rx  # skips DB integration tests if DATABASE_URL is unreachable
./scripts/test.sh                 # full integration path, requires Docker/PostgreSQL
```

Use `uv run --extra dev pytest --require-db -q -rx` when a CI or release check
must fail fast if `DATABASE_URL` is configured but unreachable.

`uv run alembic heads` does not require a live database. `uv run alembic current`
does; for local diagnostics run this first to avoid a long connection stack:

```sh
../scripts/check_db_ready.sh && uv run alembic current
```

Seed 数据不会在请求路径自动写入。开发环境如需初始化 seed，显式运行：

```sh
../scripts/seed.sh
```

`AUTO_SEED_ON_REQUEST` 默认是 `false`，生产/预发禁止打开，避免请求期隐式写数据和并发竞态。Seed 包含：

- `datong-xijindao / knife-cut-noodles-meatball`
- `korea-seongsu / shopping-street`
- 两条 deterministic `intent_answers`

这些 `intent_answers` 只是皮皮加工推荐卡时的可信参考，不会被当作最终卡片文案原样吐给 App。

## Pipi model and card composition

默认运行时使用 deterministic reasoner，便于测试和离线 benchmark 复现：

```sh
PIPI_MODEL_PROVIDER=deterministic
PIPI_CARD_COMPOSER=deterministic
```

要让 product `/v1/chat/turn` 每次都进入真实 OpenAI reasoner：

```sh
PIPI_MODEL_PROVIDER=openai
OPENAI_API_KEY=sk-YOUR_API_KEY
OPENAI_MODEL=gpt-4.1-mini
OPENAI_TIMEOUT_SECONDS=20
```

开启后，`PipiLoop` 每轮都会先调用 OpenAI，让模型输出 `tool` 或 `answer`。但工具执行边界不变：

- OpenAI 不能直接创建推荐卡或求助卡。
- OpenAI 只能选择 `allowed_tools` 里的工具。
- 推荐卡和求助卡仍必须经 `DbPipiAbilityCenter` / tool 落库。
- 如果 OpenAI 返回非法 schema、越权工具或接口失败，系统会降级到 deterministic decision，并在 `loop_trace.reasoner_decision` 里记录 `llm_status`。

Shadow mode 仍可单独用于对比，不影响 product answer：

```sh
LLM_SHADOW_ENABLED=true
LLM_PROVIDER=openai
LLM_MODEL=gpt-4.1-mini
```

LLM Query Rewrite 灰度只用于补全第一层意图闸门的结构化槽位，默认关闭。即使开启，也不会调用 AbilityCenter、不会创建推荐卡或求助卡，最终工具执行仍由 product runtime 决定：

```sh
LLM_REWRITE_ENABLED=false
LLM_REWRITE_MIN_CONFIDENCE=0.78
```

## Production Runtime Guards

V0 生产策略：

```sh
APP_ENV=production
AUTO_SEED_ON_REQUEST=false
ALLOW_EVAL_BYPASS=false
PIPI_EVAL_MODE=false
REQUIRE_DEVICE_UID=true
LANGGRAPH_CHECKPOINT_REQUIRED=false
LANGGRAPH_CHECKPOINT_BACKEND=disabled
JWT_SECRET=replace-with-long-random-secret
EMAIL_PROVIDER=smtp
EMAIL_FROM_NAME=皮皮
EMAIL_FROM_ADDRESS=no-reply@example.com
SMTP_HOST=smtp.example.com
SMTP_PORT=465
SMTP_USERNAME=no-reply@example.com
SMTP_PASSWORD=replace-with-smtp-password
SMTP_USE_SSL=true
SMTP_USE_STARTTLS=false
```

当前 V0 不支持生产强 checkpoint。`/health/ready` 在默认策略下返回 `checkpoint=not_required`；如果强行设置 `LANGGRAPH_CHECKPOINT_REQUIRED=true`，ready 会失败，生产/预发配置也会拒绝启动。

生产启动：

```sh
../scripts/migrate.sh
../scripts/start_prod.sh
```

`scripts/start_prod.sh` 使用 `uv run uvicorn`，不带 `--extra dev`。

## Email Auth

产品登录采用邮箱验证码，不支持密码登录。`device_uid` 仍是设备匿名身份；用户用邮箱验证码登录后，后端会把该设备上的匿名 conversation、turn、question、card、help_card、help_answer、light_event 等数据合并到邮箱用户。

Auth API:

- `POST /v1/auth/request-code`
- `POST /v1/auth/verify-code`
- `POST /v1/auth/refresh`
- `POST /v1/auth/logout`
- `GET /v1/auth/me`

验证码和 refresh token 只存 hash；SMTP 密码通过 `SMTP_PASSWORD` 环境变量配置，不会写入日志或响应。开发/测试环境默认 `EMAIL_PROVIDER=console`，会在响应里返回 `dev_code` 便于本地自动化；生产/预发禁止 console provider，必须配置 SMTP。

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

- 常规推荐卡必须绑定可信图；高德地点卡可以不带图片，但必须带 `place` 和 `action`。
- 可信图必须来自 `verified=true`、`displayable=true` 且 `is_ai_generated=false` 的 `image_assets`。
- 没有可信图、没有证据或置信不足时，不硬推推荐卡，生成“求一个”。
- 模型不能编图片 URL。
- 不使用 AI 生成图。

可选高德地图能力：

```sh
AMAP_WEB_SERVICE_KEY=
AMAP_SEARCH_RADIUS_METERS=1200
AMAP_SEARCH_LIMIT=20
AMAP_ROUTE_MODE_DEFAULT=walking
```

高德只用于区域选店时的 POI 搜索、距离和路线估算，不用于判断“好吃”。第一阶段不做 App 内地图，也不接 iOS 地图 SDK；点击卡片里的“高德导航”时使用高德 URI API 打开高德地图。`AMAP_WEB_SERVICE_KEY` 只保存在后端，不会写入响应、ToolCall 原始输出或前端配置。

当 `AMAP_WEB_SERVICE_KEY` 缺失时，后端不会崩溃：区域选店会回落到本地 seed / 求助卡，并在 debug 中标记 `amap_disabled=true`。

## Admin prompt configs

运营后台支持实时调整皮皮运行时策略：

```sh
ADMIN_TOKEN=change-me
```

打开：

```text
http://127.0.0.1:8788/admin/sessions
```

进入 `Prompts` 页可以编辑 `area_food_evidence_policy`。这条配置包含两部分：

- `content`: 给运营和调试人员看的策略说明。
- `config_json`: 后端实际读取的结构化策略。

保存后不需要重启服务，下一次 `/v1/chat/turn` 会直接读取数据库里的最新配置。所有读取和更新都会写入 `AdminAuditLog`。

默认策略会把“广东人 / 粤 / 广州 / 深圳”等身份或口味线索转成粤菜优先规则，并拒绝把长沙菜、湘菜、川菜、重辣火锅当作默认答案；如果高德候选里没有匹配证据，皮皮会回退到求助卡，而不是硬推不匹配的地点卡。

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
{
  "ok": true,
  "service": "just-pick-this-ios-backend",
  "version": "0.1.0",
  "env": "development",
  "eval_mode": false
}
```

## API

- `POST /v1/bootstrap`
- `POST /v1/chat/turn`
- `GET /v1/help-feed`
- `GET /v1/help-cards/{id}`
- `POST /v1/help-cards/{id}/publish`
- `POST /v1/help-cards/{id}/one-liner`
- `GET /v1/light-events`
- `GET /v1/cards/{id}`
- `POST /v1/cards/{id}/accept`

## Eval API Contract

`pipi-eval-lab` 用这组接口离线启动后端、重置评测命名空间、写入固定 seed，再通过 `/v1/chat/turn` 跑 benchmark。评测模式不接真实 Tavily、OSM、Wikidata 或线上状态。

开启方式：

```sh
PIPI_EVAL_MODE=true
PIPI_MODEL_PROVIDER=deterministic
PIPI_CARD_COMPOSER=deterministic
WEB_SEARCH_PROVIDER=disabled
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8788
```

Reset/seed：

```sh
curl -X POST http://127.0.0.1:8788/v1/eval/reset \
  -H 'content-type: application/json' \
  -d '{"eval_run_id":"2026-05-23T10-00-00Z"}'

curl -X POST http://127.0.0.1:8788/v1/eval/seed/food-beijing-onsite-v1 \
  -H 'content-type: application/json' \
  -d '{"mode":"minimal","with_approved_answers":true}'
```

本地 benchmark 示例：

```sh
curl -X POST http://127.0.0.1:8788/v1/chat/turn \
  -H 'content-type: application/json' \
  -d '{
    "device_uid":"eval-device-001",
    "conversation_id":null,
    "message":"我到了北京三里屯，有什么好吃的川菜么",
    "client_context":{
      "source":"pipi-eval-lab",
      "benchmark_suite_id":"food_beijing_onsite_v1",
      "benchmark_case_id":"area_sanlitun_sichuan",
      "eval_run_id":"2026-05-23T10-00-00Z",
      "include_debug":true
    }
  }'
```

`/v1/chat/turn` 稳定响应字段：

- `conversation_id`
- `turn_id`
- `assistant_message`
- `location_state`: `in_area | in_venue | unknown`
- `ui_events`
- `data`
- `metadata.intent`
- `metadata.agent_run_id`
- `metadata.retrieval_run_id`
- `debug`: 仅 `PIPI_EVAL_MODE=true` 且 `client_context.include_debug=true` 返回

推荐卡 schema：

```json
{
  "id": "...",
  "type": "recommendation_card",
  "version": "onsite_food_beijing_v1",
  "target_type": "restaurant | ordering_bundle | place",
  "title": "...",
  "subtitle": "...",
  "decision_factor": { "key": "...", "text": "..." },
  "image": null,
  "place": {
    "provider": "amap",
    "poi_id": "...",
    "name": "...",
    "address": "...",
    "location": { "lng": 116.45, "lat": 39.93, "coord_type": "gcj02" },
    "tel": null,
    "typecode": "050102"
  },
  "route": {
    "provider": "amap",
    "mode": "walking",
    "distance_meters": 680,
    "duration_seconds": 540,
    "summary_text": "步行约 9 分钟",
    "route_run_id": "..."
  },
  "action": {
    "type": "open_amap",
    "label": "高德导航",
    "uri": "https://uri.amap.com/navigation?..."
  },
  "provenance": {},
  "ui": {}
}
```

求助卡 schema：

```json
{
  "id": "...",
  "type": "help_card",
  "version": "onsite_food_beijing_v1",
  "status": "draft",
  "title": "...",
  "location_state": "unknown",
  "context": {},
  "wants": [],
  "avoids": [],
  "constraints": [],
  "reward": { "label": "+10", "value": 10 },
  "answer_stats": { "count": 0, "min_required": 3 },
  "revision": 1
}
```

Eval-only endpoints:

- `POST /v1/eval/reset`
- `POST /v1/eval/seed/food-beijing-onsite-v1`
- `POST /v1/eval/seed/negative-cases`
- `GET /v1/eval/seed/status`
- `GET /v1/eval/traces/conversations/{conversation_id}`
- `GET /v1/eval/traces/turns/{turn_id}`

`PIPI_EVAL_MODE=false` 时，`/v1/eval/*` 返回 `404`。

## Tests

```sh
../scripts/test.sh
```

The acceptance tests cover the chat-first loop: bootstrap, Datong Top 1, Korea help draft, publish, help feed, one-liner evidence, final card, intent answer, light event, retrieval records, and tool call records.

Harness QA targeted checks:

```sh
uv run --extra dev pytest app/tests/test_harness_input_gate.py app/tests/test_pipi_loop.py app/tests/test_ability_center.py app/tests/test_evaluator.py app/tests/test_answer_gate.py app/tests/test_context_builder.py app/tests/test_trace_store.py app/tests/test_quality_scoring.py app/eval/test_quality_scoring.py -q -rx
uv run --extra dev pytest app/tests/test_p2_finalize_graph_path.py app/tests/test_p3_finalize_tool_chain.py -q -rx
```

These checks cover non-task inputs staying out of the loop, Datong recommendation tool order, Korea help-card fallback, publish/update help-card routing, venue ordering evaluation, single `decision_factor`, `ToolResult` feedback into the next reasoner turn, full harness `loop_trace` event names, and quality report generation.

## Eval Reports

Quality reports can be generated without calling the live app if benchmark rows
are already captured as JSON/JSONL:

```sh
cd backend
uv run python ../scripts/benchmark_quality_report.py \
  --results ../benchmarks/reports/latest/results.jsonl \
  --benchmark ../benchmarks/pipi_onsite_500_v1.json \
  --out ../benchmarks/reports/latest
```

To generate evaluated product-path rows locally through FastAPI ASGI and then
write reports:

```sh
cd backend
uv run python ../scripts/run_product_benchmark.py \
  --benchmark ../benchmarks/pipi_onsite_500_v1.json \
  --out ../benchmarks/reports/latest \
  --limit 100
```

This writes `results.jsonl`, `results_guard_report.*`, `quality_report.*`, and
the other eval reports. The runner forces product mode:
`ALLOW_EVAL_BYPASS=false`, `PIPI_EVAL_MODE=false`, and shadow disabled.
It requires a reachable `DATABASE_URL`; if the database is missing or
unreachable it writes a blocked `product_benchmark_summary.*` instead of a
partial result set.

For schema/coverage-only checks:

```sh
cd backend
uv run python ../scripts/benchmark_quality_report.py \
  --benchmark ../benchmarks/pipi_onsite_500_v1.json \
  --out ../benchmarks/reports/schema-check
```

The report writer emits:

- `quality_report.json`
- `quality_report.md`
- `case_quality_scores.jsonl`
- `low_quality_cases.md`
- `seed_gap_report.md`
- `pipi_agent_improvement_report.md`
- `benchmark_coverage_report.md`
- `generated/index.md`
- `generated/issuer_*.md`
- `generated/p2_aggregate.md`

Run the release-quality gate after generating reports:

```sh
cd backend
uv run python ../scripts/validate_benchmark_results.py \
  --results ../benchmarks/reports/latest/results.jsonl \
  --require-latency-ms \
  --out ../benchmarks/reports/latest

uv run python ../scripts/quality_gate.py \
  --report-dir ../benchmarks/reports/latest \
  --min-pass-rate 0.95 \
  --min-average-quality 0.82 \
  --max-p50-latency-ms 3500 \
  --max-p95-latency-ms 6000 \
  --max-p0 0 \
  --max-p1 0
```

The gate emits:

- `results_guard_report.json`
- `results_guard_report.md`
- `quality_gate_report.json`
- `quality_gate_report.md`

Use `--min-shadow-schema-valid-rate 0.98` when the report directory includes
`shadow_comparison_report.json` from an LLM shadow run.

Latency gates require evaluated benchmark rows with `latency_ms`. If a latency
threshold is provided but the report has no latency data, the gate fails instead
of silently passing. Coverage-only smoke reports intentionally do not enable
latency thresholds.

For a local no-DB smoke check of the report writer plus gate:

```sh
../scripts/test_quality_gate.sh
```

CI uploads the smoke output as the `quality-gate-smoke-report` artifact. When
`benchmarks/reports/latest/results.jsonl` is present, CI also runs the strict
gate and uploads `quality-gate-strict-report`.

## Admin Trace

The internal admin console is protected by `ADMIN_TOKEN`:

```sh
ADMIN_TOKEN=change-me
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8788
```

Open:

```text
http://127.0.0.1:8788/admin/sessions
```

Useful read paths:

- `GET /admin/api/sessions`
- `GET /admin/api/sessions/{conversation_id}`
- `GET /admin/api/traces`
- `GET /admin/api/traces/{trace_id}`
- `GET /admin/api/metrics/overview`
- `GET /admin/api/metrics/activity`
- `GET /admin/api/metrics/funnel`
- `GET /admin/api/metrics/failures`
- `GET /admin/api/content/tasks`
- `GET /admin/api/prompts/{prompt_key}/versions`
- `POST /admin/api/prompts/{prompt_key}/replay`
- `POST /admin/api/prompts/{prompt_key}/rollback`

Admin requests must send `Authorization: Bearer <ADMIN_TOKEN>`. Query-string
tokens and `x-admin-token` are intentionally rejected so credentials do not
land in URLs, browser history, or proxy logs.

Session detail returns turns and `AgentRun` traces. Trace detail includes
graph output, `loop_trace`, retrieval runs/hits, and tool calls so an operator
can replay why Pipi answered, created a card, or drafted help.

The ops console also exposes live registration/activity/funnel/failure metrics,
content review queues, image/help-card operation views, and prompt replay /
rollback. Prompt replay is offline and audit-only: it creates a
`prompt_replay_runs` row, but does not call `/v1/chat/turn` or create runtime
business rows. Prompt rollback creates a new active prompt version instead of
mutating historical `agent_prompt_config_versions`.

## Rules

- `/v1/chat/turn` is the product entry.
- `PipiChatGraph` is the outer workflow/checkpoint wrapper.
- `PipiLoop` is the single-turn agent engine for tool-capable turns.
- The reasoner outputs only `tool` or `answer`.
- Tool execution must cross the AbilityCenter boundary used by the chat path.
- `ToolResult` must feed the next reasoner iteration.
- Greeting/smalltalk/app-help/unknown do not enter the tool loop.
- Recommendation cards and help cards are tool calls.
- “来一句” is human evidence, not the final answer.
- Final answers are produced by `PipiFinalizeGraph`.
- All runtime state is persisted in PostgreSQL.
- `intent_answers` 是参考证据，不是最终答案；皮皮会按当前问题重新组织卡片文案。
- V0 使用 deterministic reasoner/model adapter；真实 LLM 后续只通过替换 `ModelAdapter` 接入。
- 不使用 AI 生成图片；模型不能编图片 URL。
- 推荐卡必须绑定 verified、displayable、非 AI 的 `image_assets`；不满足时生成“求一个”。
