# legacy_card_fields_plan.md

## 结论

本轮不删除任何 DB 字段，只把默认 API/serializer 收口到 v2 推荐卡契约：

- 默认响应保留卡片身份、状态、图片、地点/路线/action、`item`、单个 `decision_factor`、`evidence_ids`、`provenance`、`ui`。
- 默认响应不再返回 legacy 展示字段：`reasons`、`bullets`、`followups`、`warning`。
- `create_recommendation_card` 工具拒绝 legacy 展示字段，避免新写入继续污染。
- 旧存储字段仍留作兼容和后续 migration 依据。

## 字段清单

| 字段 | 位置 | 默认 API 是否返回 | 前端/测试使用情况 | 建议 |
| --- | --- | --- | --- | --- |
| `bullets_json` | `backend/app/models/runtime.py` 的 `RecommendationCard.bullets_json`；老写入点会写空数组 | 否。`backend/app/services/runtime.py::serialize_card` 已不输出 `bullets` | 现有测试只验证 forbidden / strip；没有产品路径依赖默认返回 | 保留 DB 字段兼容历史数据，标记 deprecated；后续 migration 确认无旧客户端后删除 |
| `bullets` | 老工具参数、`CardDraft`、旧 payload 兼容字段 | 否。`CardSummary` / `CardDetail` 会剥离 | 测试用于确认 forbidden；运行时不应写入 | tool 层继续拒绝；composer 后续改为只产 `decision_factor` |
| `followups` | `payload_json.followups`、`CardDraft.followups`、旧 composer prompt | 否。`serialize_card` 已不输出；schema 会剥离 | 测试用于确认 forbidden；默认 API 不依赖 | 保留读取兼容但不默认返回；后续清理 `CardDraft` |
| `reasons` | 旧工具参数 / 旧 payload 形态 | 否。schema 会剥离 | 测试用于确认 forbidden；无默认消费者 | 继续拒绝写入；无需 DB migration |
| `warning` | `RecommendationCard.warning` DB 字段、`CardDraft.warning`、旧 composer prompt | 否。`serialize_card` 已不输出；schema 会剥离 | 当前测试只把它当 forbidden 字段；无默认 API 依赖 | 保留 DB 字段，标记 deprecated；后续迁移删除或改进到 evaluator metadata |
| old card composer | `backend/app/agent/card_composer.py::CardDraft` 仍产 `bullets/warning/followups`；`backend/app/services/chat.py` 中 old composer 路径只把 `title/subtitle/reason/confidence` 写入卡，`bullets_json=[]`、`warning=None` | 否 | 仍可能被旧检索/推荐路径调用，但默认 serializer 已隔离 legacy 展示字段 | 不在本轮大改；下一轮把 `CardDraft` 改为 `item + decision_factor` 形态 |

## 已加防线

1. `backend/app/tools/recommendation.py`
   - `create_recommendation_card` 拒绝 `reasons`、`bullets`、`followups`、`warning`。

2. `backend/app/ability/tools/recommendation.py`
   - generic AbilityCenter adapter 同样拒绝 `reasons`、`bullets`、`followups`、`warning`。

3. `backend/app/services/runtime.py`
   - `serialize_card` 默认不输出 `bullets`、`warning`、`followups`。

4. `backend/app/schemas/cards.py`
   - `CardSummary` / `CardDetail` 在 response model 层剥离 `reasons`、`bullets`、`followups`、`warning`。

## 未删除原因

- `recommendation_cards.bullets_json` 和 `recommendation_cards.warning` 是历史 DB 字段，直接删除会影响旧数据和 Alembic 兼容。
- `CardDraft` 仍服务老 composer fallback；直接改动会扩大风险。
- 当前目标是“默认 API v2 contract 不暴露 legacy”，不是一次性 schema migration。

## 后续建议

1. 新增 migration 前先跑线上/测试库扫描，确认 `bullets_json`、`warning` 是否有非空历史数据。
2. 将 `CardDraft` 改为只包含 `item`、`decision_factor`、`confidence`、metadata。
3. 如果存在旧客户端需要 legacy，可新增显式参数或独立 legacy endpoint，不要污染默认 `/v1/cards/{id}`。
