# 就选这个

iOS-first 的旅行决策 App。用户不想查攻略、不想比较多个选项时，只说一句「我在哪，我想干什么」，AI 管家「皮皮」直接给一个选择；如果皮皮不敢硬选，就生成「求一个」，让懂的人「来一句」，再由皮皮汇总成最终答案。

## iOS 截图

<p align="center">
  <img src="docs/images/ios-home.png" width="190" alt="首页输入" />
  <img src="docs/images/ios-top1-card.png" width="190" alt="Top 1 推荐卡" />
  <img src="docs/images/ios-help-card.png" width="190" alt="求一个求助卡" />
  <img src="docs/images/ios-answer-card.png" width="190" alt="来一句答主卡" />
</p>

## 一句话

```text
输入 -> 皮皮给 Top 1 -> 不确定就求一个 -> 别人来一句 -> 皮皮汇总最终答案 -> 用户采纳
```

## App 基础框架

当前 iOS 端已经补齐三个主入口：

- `皮皮`：提问、推荐卡、求一个、历史会话。
- `来一句`：刷求一个卡片并提交一句话。
- `我的`：账号、积分、回答数、我的求一个、最近选择和消息。

`我的` 页面会读取：

- `GET /v1/rewards/me`
- `GET /v1/answerers/me/quality`
- `GET /v1/light-events`

API 地址可以通过 `Info.plist` 中的 `API_BASE_URL` 配置。

## 当前版本

- iOS：SwiftUI 原生 App，iOS first。
- Backend：Python 3.11+ FastAPI + LangGraph Python + SQLAlchemy + Alembic + PostgreSQL。
- Agent：皮皮，V0 默认 deterministic adapter，可选 DeepSeek 对数据库参考答案做二次加工。
- 主入口：`POST /v1/chat/turn`。
- 状态：conversation、turn、agent run、tool call、retrieval、intent answer、card、help card、answer、light event 都落库。
- 图片：推荐卡优先绑定 verified、displayable 且 `is_ai_generated=false` 的 `image_assets`；没有可信图时仍可返回 `image=null`。
- 旧版 Node 后端：保留在 `backend-node-legacy/`，仅作参考。

## 产品说明书

### 1. 首页输入

用户输入一句自然语言，例如：

```text
我现在在大同喜晋道，不知道吃什么
```

iOS 调用：

```http
POST /v1/chat/turn
```

后端做三件事：

- 创建或恢复 user / conversation。
- 写入用户 turn。
- 进入 `PipiChatGraph`。

### 2. Top 1 推荐卡

当皮皮能确定答案时，调用工具：

```text
create_recommendation_card
```

卡片返回给 iOS 的核心内容：

- 标题：这次只给一个选择。
- 副标题：为什么适合当前问题。
- 理由：短解释，不做长攻略。
- 要点：最多几条能帮助用户放心采纳的信息。
- 避雷：明确什么情况下别选。
- 图片：优先引用数据库 `ImageAsset.id`；如果库里没有合适图，可用 Tavily 找真实网页引用图候选。
- 无图：如果没有可信引用图，推荐卡仍然生成，返回 `image=null`。

用户可以：

- 点绿色采纳：问题完成，进入历史记录。
- 点红色不采纳：转成求一个。
- 继续追问一句。
- 问真人。

### 3. 求一个求助卡

当皮皮不敢硬选，或用户主动「问真人」，调用工具：

```text
draft_help_card
```

求助卡不是社区帖子首页，也不是信息流，它是当前问题的一个待发布卡片。

求助卡字段：

- `title`：把用户问题改写成别人能快速理解的一句话。
- `context_text`：皮皮说明缺少什么信息、为什么不硬选。
- `missing_info`：缺失偏好、预算、位置、风格等。
- `status=draft`：待发布，用户还能补一句背景。

用户点「发出去」后调用：

```text
publish_help_card
```

状态变化：

```text
draft -> published / collecting
```

发出去之后不能反悔，用户回到首页，等后台亮灯。

### 4. 来一句答主卡

答主从首页右上角「来一句」进入内容池。这里不是完整社区，也没有信息流，只展示一个需要帮忙的求助卡。

答主只能提交一句话：

```text
别去明洞当背景板，去圣水。
```

iOS 调用：

```http
POST /v1/help-cards/{id}/one-liner
```

后端写入：

```text
HelpAnswer
```

注意：来一句只是 human evidence，不是最终答案。它不会直接变成用户看到的最终推荐卡。

### 5. 最终答案和亮灯

当一个求助卡累计到足够答案：

```text
answer_count >= min_answers_required
```

触发：

```text
PipiFinalizeGraph
```

最终流程：

- 读取 help card。
- 读取所有 one-liner answers。
- 再检索数据库里的意图答案、历史卡片、图片资产。
- 调用 `create_recommendation_card` 生成最终卡。
- 调用 `save_intent_answer` 把这次新答案沉淀回数据库。
- 调用 `light_user` 给提问用户亮灯。

用户下次打开或轮询到亮灯事件后，可以回到最终推荐卡并采纳。

## Agent 架构

```mermaid
flowchart TD
    A[iOS SwiftUI App] --> B["POST /v1/chat/turn"]
    B --> C[FastAPI]
    C --> D[(PostgreSQL)]
    C --> E[PipiChatGraph]
    E --> F[ingest_turn]
    F --> G[retrieve_knowledge]
    G --> D
    G --> H[decide_next_action]
    H --> I{Tool Call}
    I --> J[create_recommendation_card]
    I --> K[draft_help_card]
    I --> L[publish_help_card]
    I --> M[submit_one_liner_answer]
    K --> N[Help Feed]
    M --> O[PipiFinalizeGraph]
    O --> P[finalize_help_card]
    P --> Q[save_intent_answer]
    Q --> R[light_user]
    J --> S[UI Events]
    K --> S
    L --> S
    R --> S
    S --> A
```

## 关键规则

- 主流程是 chat，不是传统推荐 API。
- 推荐卡和求助卡必须由 tool call 创建。
- 模型不能绕过工具直接吐卡片 JSON。
- 数据库里的 `intent_answers` 是可信参考，不是最终文案。
- DeepSeek / web search 只能作为加工和补充证据层。
- 图片不是强制字段；有可信引用图就挂卡，没有就 `image=null`。
- 图片可以来自库内 curated 资产，也可以来自 Tavily 检索后落库的真实网页引用图候选。
- 前端遇到图片加载失败时自动退化成文本卡或来源入口，不显示破图图标或失败占位。
- 不允许 AI 生成图。
- 不允许模型自己编图片 URL。
- 支持邮箱验证码登录；未登录时继续用 `device_uid` 表示一个手机，登录后把设备匿名数据合并到邮箱账号。
- iOS 当前采用 Chat-first 产品壳：启动直接进入皮皮聊天，左侧 Drawer 承载历史、来一句、我的求一个、我的回答、收藏、奖励、消息中心和账号入口；不再使用底部 Tab，也不做社区信息流和 Top 3。
- iOS 设计系统集中维护颜色、间距、圆角和字号 token；核心 Typography token 使用系统文本样式，随 Dynamic Type 放大缩小。
- iOS 设计系统提供最小触控区域 token；顶部、Drawer、地点选择和追问 chip 等关键入口按 44pt 触控建议收口。
- Drawer 历史会话支持搜索、置顶、重命名、删除确认和短暂撤销；删除只移除本机抽屉记录，避免误触直接消失。
- 关键动作使用轻触感反馈：发送、采纳、发布、滑卡、Drawer 打开/关闭、置顶、重命名、删除与恢复会话都有明确但克制的反馈。
- iOS 会尊重系统“减少动态效果”：Drawer 和来一句 Deck 会收敛缩放、旋转和弹簧位移，保留可操作性。
- 收藏页支持查看推荐卡和已采纳结果，取消收藏后会给出短暂撤销，避免误触丢失。
- 「求一个」支持草稿、收集中、已有结果、已完成和已关闭状态；「我的求一个」会分别展示各状态数量，并支持按状态筛选记录。用户可以主动关闭当前求助，关闭后仍能回看。
- 「求一个」发布失败时保留草稿，不再假装成功；聊天页和详情页都会给出可重试的短错误提示。
- 「我的回答」支持按待采纳、已采纳和未采用筛选本机提交记录；空筛选态会给出短说明和继续来一句入口。
- 奖励页支持按待确认、已获得和未采用筛选明细，`+10` 不再只是孤立数字。
- 消息中心会保留有人回答、结果完成和奖励变化提醒；打开消息页不自动清红点，点击单条或“全部已读”后才标记已读。
- 求助卡会展示当前状态、回答数量说明和奖励，不再只显示一个孤立的发布标签。
- 推荐卡理由支持折叠展开；产品页标题、副标题和消息行都做了限行，超长文本不再撑爆布局。
- 决策地点支持当前定位、常用地点和手动输入；当前选中的地点会保存在本机，下一次启动或新对话继续用于 `/v1/chat/turn`。
- 推荐卡的“就这个 / 不合适 / 信息有误”会写回后端；负反馈在卡片菜单内有本地已标记状态，避免重复点击。
- 账号设置支持邮箱登录、退出登录、清除本机记录和删除账号；清除本机记录不会退出邮箱登录。

## 目录

```text
just-pick-this-ios/
  NativeApp/                 # SwiftUI iOS App
  backend/                   # Python Agent Backend
  backend-node-legacy/        # 旧 Node 后端参考
  docs/images/                # README iOS 截图
  JustPickThisIOS.xcodeproj
```

## 后端启动

```sh
cd backend
uv sync --extra dev
cp .env.example .env
```

编辑 `backend/.env`：

```sh
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/just_pick_this_agent_v0
PIPI_CARD_COMPOSER=deterministic
```

初始化数据库：

```sh
uv run alembic upgrade head
```

启动服务：

```sh
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8788
```

健康检查：

```sh
curl http://127.0.0.1:8788/health
```

期望返回：

```json
{"ok": true}
```

## 可选 AI 加工

默认离线模式：

```sh
PIPI_CARD_COMPOSER=deterministic
```

启用 DeepSeek：

```sh
PIPI_CARD_COMPOSER=deepseek
DEEPSEEK_API_KEY=...
DEEPSEEK_MODEL=deepseek-reasoner
```

## iOS 决策地点

聊天页顶部会显示当前“决策地点”。用户可以手动输入城市、区域或地标，也可以主动点击“使用当前定位”。App 不会在每次发送消息时自动请求定位；只有用户选择当前定位时才触发系统授权。若系统没有返回定位，地点面板会提供“去设置”和手动输入两条兜底路径。

发送 `/v1/chat/turn` 时，iOS 会把可见地点写入 `client_context.decision_location`。如果用户只补了一句“我想吃川菜”这类缺地点表达，后端 InputGate 会优先使用这个显式地点继续推荐链路。

可选 web search：

```sh
WEB_SEARCH_PROVIDER=tavily
TAVILY_API_KEY=tvly-YOUR_API_KEY
TAVILY_SEARCH_MAX_RESULTS=5
TAVILY_IMAGE_MAX_RESULTS=8
TAVILY_TIMEOUT_SECONDS=8
```

Tavily 的用途：

- 给皮皮补充网页事实和引用来源。
- 用 `include_images` 找真实网页引用图候选。
- 所有图片候选先落库，默认 `verification_status=candidate`。
- 只有 verified、displayable、非 AI 的图片才能挂到推荐卡。

无论是否启用 AI 或 web search，最终卡片仍必须通过 tool call 创建。图片不是强制字段；无可信图时卡片返回 `image=null`。

## iOS 运行

```sh
./scripts/build_ios_sim.sh
```

`scripts/build_ios_sim.sh` 会自动选择一个可用 iPhone Simulator 的
destination id；如果要固定设备，可设置 `IOS_SIMULATOR_ID=<device-id>`。

也可以直接用 Xcode 打开：

```text
JustPickThisIOS.xcodeproj
```

App 默认连接：

```text
http://127.0.0.1:8788
```

## 截图复现

Debug 包支持文档截图启动参数：

```sh
xcrun simctl launch booted com.justpickthis.ios --demo-screen=result
xcrun simctl launch booted com.justpickthis.ios --demo-screen=ask
xcrun simctl launch booted com.justpickthis.ios --demo-screen=answer
```

截图命令：

```sh
xcrun simctl io booted screenshot docs/images/ios-help-card.png
```

## 核心接口

### Bootstrap

```http
POST /v1/bootstrap
```

```json
{
  "device_uid": "ios-demo-device",
  "platform": "ios",
  "app_version": "0.1.0"
}
```

### Chat Turn

```http
POST /v1/chat/turn
```

```json
{
  "device_uid": "ios-demo-device",
  "message": "我在大同喜晋道，不知道吃什么"
}
```

可能返回：

- `show_recommendation_card`
- `show_help_card_draft`
- `help_card_published`
- `light_event`

### Help Feed

```http
GET /v1/help-feed?device_uid=ios-answer-user&limit=10
```

规则：

- 不返回 owner 自己的求助卡。
- 不返回自己已经回答过的求助卡。
- 优先返回 answer_count 少的卡。

### One-liner

```http
POST /v1/help-cards/{id}/one-liner
```

```json
{
  "device_uid": "ios-answer-user",
  "text": "别去明洞当背景板，去圣水。"
}
```

### Light Events

```http
GET /v1/light-events?device_uid=ios-demo-device
```

### Accept Card

```http
POST /v1/cards/{id}/accept
```

## 数据对象

核心表：

- `User`
- `Conversation`
- `Turn`
- `AgentRun`
- `ToolCall`
- `RetrievalRun`
- `RetrievalHit`
- `Intent`
- `IntentAnswer`
- `ImageAsset`
- `Question`
- `RecommendationCard`
- `HelpCard`
- `HelpAnswer`
- `LightEvent`

关键状态：

```text
Question: received -> top1_ready / ask_draft_ready -> help_published -> final_ready -> completed
HelpCard: draft -> published -> collecting -> final_ready -> closed
RecommendationCard: ready -> accepted / dismissed
```

## 测试

后端：

```sh
./scripts/test.sh
```

## 密钥安全

真实 API key 只放本机 `.env` 或部署环境变量，不能进仓库、zip 包、README、测试 fixture 或 legacy 目录。任何真实 OpenAI/Tavily token 一旦进入可分享产物，都按已泄露处理，需要立即 rotate。

iOS：

```sh
xcodebuild \
  -project JustPickThisIOS.xcodeproj \
  -scheme JustPickThisIOS \
  -configuration Debug \
  -destination 'platform=iOS Simulator,name=iPhone 16 Pro' \
  CODE_SIGNING_ALLOWED=NO \
  build
```

## Demo 数据

后端启动时会幂等 seed：

- 图片资产：`datong-xijindao / knife-cut-noodles-meatball`
- 图片资产：`korea-seongsu / shopping-street`
- 意图答案：大同喜晋道到店不知道点什么 -> 刀削面 + 肉丸子
- 意图答案：韩国逛街不去明洞想小众 -> 去圣水

这些数据只作为皮皮检索和加工的参考，不是前端 mock，也不是最终卡片硬编码。

## 产品化进度

- `STATE-002`: 可重试的发送失败会保留原输入并提供重试入口；原文未改时重试不会重复插入同一条用户气泡。
- `POLISH-007`: 推荐图、Drawer 历史、来一句 Deck、产品列表的加载骨架会尊重系统“减少动态效果”。
