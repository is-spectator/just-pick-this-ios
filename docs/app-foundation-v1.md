# App Foundation V1

本轮补齐 iOS App 的基础使用框架，不改皮皮 Agent 和后端协议。

> 2026-06 产品化更新：早期“三 Tab”壳已经被 Chat-first App Shell 取代。App 启动后直接进入皮皮聊天；来一句、我的求一个、收藏、奖励和账号入口统一收进左侧 Drawer。

## 新增

- 单一 Chat 主界面：顶部菜单 / 皮皮 / 新对话，底部 Composer。
- 左侧 Drawer：搜索、新对话、来一句、我的求一个、收藏、奖励、置顶、最近和账号入口。
- 我的页面：账号、积分、回答次数、历史、求一个、消息和版本，作为 Drawer 里的账号/设置入口承载。
- Profile API 聚合：奖励、答主质量、亮灯消息。
- API Base URL 改为可由 Info.plist 配置。

## 验证

- Xcode Debug simulator build 通过。
- iPhone 16 Pro Simulator 视觉验收：首页无底部 TabBar，第一眼为聊天界面。
- 后端 unit test 保持独立验证。
