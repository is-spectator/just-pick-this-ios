# IntentAnswer Admin Import Report

Date: 2026-06-24

## Issue

`pipi_effect_iteration_issues.xlsx` 中的 `ISS-013 Intent Memory` 要求 IntentAnswer 具备可运营的长期记忆能力，包括：

- `success_count`
- `rejection_count`
- `last_used_at`
- 后台编辑
- 后台导入

现状中，`IntentAnswer` 已经有成功/拒绝/最近使用字段，且后台通用表格编辑已经覆盖 `intent_answers`。缺口是：运营从 seed gap 或人工整理结果批量导入时，没有一个明确、幂等、默认不污染产品检索的导入工作流。

## Change

新增专用后台接口：

```text
POST /admin/api/intent-answers/import-drafts
```

请求：

```json
{
  "items": [
    {
      "intent_key": "area:北京:五道口:韩餐",
      "intent_text": "北京五道口韩餐",
      "answer_title": "五道口韩餐，就选这家",
      "answer_summary": "五道口想吃韩餐，优先选距离近、翻台稳定的一家。",
      "constraints": {
        "city": "北京",
        "area": "五道口",
        "cuisine": "韩餐"
      },
      "source_ref_id": "manual-seed-001",
      "confidence": 0.82,
      "tags": ["area_food", "seed_candidate"]
    }
  ]
}
```

响应返回导入后的 `IntentAnswer` 草稿列表。

## Safety

- 默认 `is_active=false`，不会进入产品检索。
- 以 `source_type + source_ref_id` 幂等更新同一条 `IntentAnswer`。
- 写入 `AdminAuditLog.action=import_intent_answer_drafts`。
- 只有 `admin` / `content_ops` 可调用。
- 如需上线，仍通过现有后台表编辑显式激活。

## Files

- `backend/app/services/intent_answer_import.py`
- `backend/app/admin/routes.py`
- `backend/app/tests/test_admin_eval_review_api.py`

## Validation

本地无 PostgreSQL，DB 集成测试被 pytest 自动跳过；CI 会执行真实 DB 路径。

已本地执行：

```text
python -m py_compile backend/app/admin/routes.py backend/app/services/intent_answer_import.py
uv run --extra dev pytest app/tests/test_admin_eval_review_api.py -q -rx
```

`test_admin_eval_review_api.py` 在本地显示为 DB skip，符合当前本地环境预期。
