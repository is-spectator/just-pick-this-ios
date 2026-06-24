# App Foundation V1

本轮补齐 iOS App 的基础使用框架，不改皮皮 Agent 和后端协议。

## 新增

- 三个 Tab：皮皮、来一句、我的。
- 我的页面：账号、积分、回答次数、历史、求一个、消息和版本。
- Profile API 聚合：奖励、答主质量、亮灯消息。
- API Base URL 改为可由 Info.plist 配置。

## 验证

- Swift 源码通过 `swiftc -frontend -parse` 语法解析。
- 后端 unit test：31 passed。
- 当前 Linux 环境无法运行 Xcode/iOS Simulator，因此仍需在 macOS/Xcode 做最终编译和视觉验收。
