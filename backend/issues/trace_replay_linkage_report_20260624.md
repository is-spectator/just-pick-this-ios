# Trace Replay Linkage Report

Date: 2026-06-24

## Issue

`pipi_effect_iteration_issues.xlsx` 中 `ISS-007 Trace Replay` 的验收是：

- 每个 benchmark result 都有 trace。
- Ops 后台能显示 loop_trace。
- 低质 case 能从 case 一跳到 trace / tool_call / loop_trace。

现状中 `/v1/chat/turn` 已经持久化 `AgentRun.output_json.loop_trace`，后台也有：

```text
GET /admin/api/traces/{trace_id}
```

缺口是 eval review 的 low-quality case 和 case detail 返回值里没有稳定的 trace replay payload，运营仍需要手工从不同字段里找 `agent_run_id`。

## Change

`backend/app/services/eval_review_service.py` 新增 `trace_replay` payload，并挂到：

- `low_quality_cases(...)` 每条 item
- `case_detail(...)`

字段：

```json
{
  "trace_available": true,
  "trace_id": "agent-review",
  "agent_run_id": "agent-review",
  "conversation_id": "conversation-review",
  "turn_id": "turn-review",
  "retrieval_run_id": "retrieval-review",
  "runtime_path": "product",
  "admin_trace_api_path": "/admin/api/traces/agent-review",
  "admin_session_api_path": "/admin/api/sessions/conversation-review",
  "loop_trace_expected": true
}
```

生成的 `issuer_*.md` 也新增：

```text
admin_trace_api_path
```

## Safety

- 不修改 product runtime。
- 不修改 PipiLoop。
- 不改变 benchmark 判分。
- 只增强 eval/admin 可回放性。

## Tests

新增：

```text
backend/app/tests/test_eval_review_trace_replay.py
```

覆盖：

- low-quality cases 返回 `trace_replay.admin_trace_api_path`
- case detail 返回 `trace_replay.admin_session_api_path`
- `runtime_path=product`
- `loop_trace_expected=true`

