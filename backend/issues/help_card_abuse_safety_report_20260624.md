# HelpCard Abuse Safety Report

Date: 2026-06-24

## Issue

`pipi_effect_iteration_issues.xlsx` 中 `ISS-024 Abuse Safety` 的验收是：

- 高风险内容不进 feed。
- 有审计记录。

此前已有一轮只覆盖了「来一句」的安全队列：危险/低质 one-liner 会被拒绝并写入 `ContentReviewTask`。本轮补齐求助卡本体进入公开 feed 前的安全闸。

## Change

新增保守检测：

```text
detect_help_card_abuse(...)
```

覆盖明显高风险内容：

- 联系方式/外部联系：`加我`、`vx...`、`微信号`、链接等
- 成人骚扰：`约炮`、`裸聊`
- 明确违法请求：`买毒`、`贩毒`、`办假证`、`偷拍视频`
- 隐私伤害：`人肉`、`开盒`、`身份证号`、`手机号`、`家庭住址`

变更路径：

- `POST /v1/help-cards/{id}/publish`
  - 发现危险求助卡时返回 `422 help_card_unsafe`
  - 写入 `ContentReviewTask(task_type=help_card_rejected)`
  - 不发布到 feed
- `GET /v1/help-feed`
  - 过滤历史遗留的危险 published/collecting help card

## Non-goals

- 不接外部 moderation 服务。
- 不扩大到模糊表达审查。
- 不改 iOS。
- 不改推荐/求助卡生成策略。

## Tests

新增/更新：

- `backend/app/tests/test_one_liner_quality.py`
  - 检测 help card 联系方式/违法请求
  - 正常求助卡不误伤
- `backend/app/tests/test_help_deck_api.py`
  - 发布危险 help card 被阻止并写审核任务
  - 历史危险 help card 不出现在 feed

本地 DB 不可用时，`test_help_deck_api.py` 按项目规则 skip；CI 会跑真实 DB 路径。

