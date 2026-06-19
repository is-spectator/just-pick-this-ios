# 就选这个 Backend V0 Legacy

这是早期 Node/Fastify 后端，仅作历史参考；当前产品后端在 `backend/`。

Fastify + Prisma + PostgreSQL 后端。正式接口是 `/v1/*`，旧 `/api/*` 只为当前 iOS 版本临时兼容。

## 安装

```sh
cd backend-node-legacy
npm install
cp .env.example .env
```

## 配置

`.env`:

```sh
DATABASE_URL=postgresql://USER:PASSWORD@localhost:5432/just_pick_this_v0
DEEPSEEK_API_KEY=sk-YOUR_API_KEY
DEEPSEEK_MODEL=deepseek-reasoner
MODEL_PROVIDER=deepseek
PORT=8787
```

测试环境会自动使用 mock 皮皮模型，不会请求 DeepSeek。

## 数据库

```sh
createdb just_pick_this_v0
npx prisma generate
npx prisma migrate dev --name init
npm run seed
```

seed 会创建两个已验证、非 AI 生成的 `image_assets`：

- `datong-xijindao / knife-cut-noodles-meatball`
- `korea-seongsu / shopping-street`

Top1Card 只能引用 `ImageAsset.id`，不能让模型编图片 URL。

## 开发

```sh
npm run typecheck
npm test
npm run dev
```

健康检查：

```sh
curl http://127.0.0.1:8787/health
```

## API 示例

Bootstrap:

```sh
curl -X POST http://127.0.0.1:8787/v1/bootstrap \
  -H 'Content-Type: application/json' \
  -d '{"device_uid":"ios-sim-1","platform":"ios","app_version":"0.1.0"}'
```

提交问题：

```sh
curl -X POST http://127.0.0.1:8787/v1/questions \
  -H 'Content-Type: application/json' \
  -d '{"device_uid":"ios-sim-1","text":"我现在在大同喜晋道，不知道吃什么"}'
```

发布求一个：

```sh
curl -X POST http://127.0.0.1:8787/v1/help-requests/{id}/publish \
  -H 'Content-Type: application/json' \
  -d '{"device_uid":"ios-sim-1"}'
```

拉取来一句内容池：

```sh
curl 'http://127.0.0.1:8787/v1/help-feed?device_uid=answerer-1&limit=10'
```

提交一句：

```sh
curl -X POST http://127.0.0.1:8787/v1/help-requests/{id}/answers \
  -H 'Content-Type: application/json' \
  -d '{"device_uid":"answerer-1","text":"别去明洞当背景板，去圣水。"}'
```

轮询亮灯：

```sh
curl 'http://127.0.0.1:8787/v1/light-events?device_uid=ios-sim-1'
```

采纳卡片：

```sh
curl -X POST http://127.0.0.1:8787/v1/cards/{cardId}/accept \
  -H 'Content-Type: application/json' \
  -d '{"device_uid":"ios-sim-1"}'
```

## 状态机

Question.status:

- `received`
- `pipi_processing`
- `top1_ready`
- `ask_draft_ready`
- `help_published`
- `collecting_answers`
- `finalizing`
- `final_ready`
- `completed`

HelpRequest.status:

- `draft`
- `published`
- `collecting`
- `finalizing`
- `final_ready`
- `closed`

HelpAnswer.status:

- `submitted`
- `used`
- `rejected`

Top1Card.status:

- `ready`
- `accepted`
- `dismissed`

## 兼容接口

当前 iOS 仍可使用：

- `POST /api/sessions`
- `GET /api/sessions/:id`
- `POST /api/recommend`
- `GET /api/help-requests`
- `POST /api/help-requests`
- `GET /api/help-requests/:id`
- `POST /api/help-requests/:id/answers`
- `POST /api/sessions/:sessionId/questions/:questionId/complete`

这些接口会写入同一套 PostgreSQL 数据表。后续 iOS 改到 `/v1/*` 后可以移除。
