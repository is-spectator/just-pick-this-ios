# Stability Follow-up Report

## 结论

本轮只处理上线 hardening 的 5 个遗留问题，没有改 iOS、没有改 Agent 决策逻辑、没有新增产品功能。

## Admin Auth Before DB

已修复。

- `backend/app/admin/routes.py` 给 admin router 增加前置 auth dependency。
- 未授权请求在解析 `get_db_session` 前直接返回 401。
- Admin API 仍只接受 `Authorization: Bearer <ADMIN_TOKEN>`。
- `?token=` 和 `x-admin-token` 继续返回 401。

覆盖测试：

- `test_admin_unauthorized_does_not_touch_database`
- `test_admin_requires_bearer_token_only`

## Security Gate Without DB

已新增 `scripts/test_security_gate.sh`。

该脚本会 unset `DATABASE_URL`，不启动 Docker，只运行安全前置闸门测试：

- `test_production_config_guard.py`
- `test_admin_debug_security.py`
- `test_checkpoint_runtime_guard.py`

验证结果：通过，16 tests。

## Checkpoint Strategy

最终选择策略 A：V0 不支持生产强 checkpoint。

明确规则：

- `LANGGRAPH_CHECKPOINT_REQUIRED=false`
- `LANGGRAPH_CHECKPOINT_BACKEND=disabled`
- `/health/ready` 默认返回 `checkpoint=not_required`
- production/staging 若设置 `LANGGRAPH_CHECKPOINT_REQUIRED=true`，配置校验失败
- 如果运行时被强行构造出 required checkpoint，startup guard 仍会拒绝启动

文档已在 `backend/README.md` 和 `backend/.env.example` 中说明。

## start_prod Without Dev Extra

已修复。

- `scripts/start_prod.sh` 从 `uv run --extra dev uvicorn ...` 改为 `uv run uvicorn ...`
- README 已区分开发/测试依赖和生产启动方式。

覆盖测试：

- `test_prod_start_script_does_not_use_dev_extra`

## Debug Token Bearer Only

已修复。

- `backend/app/debug/routes.py` 删除 `x-debug-token` 支持。
- Debug routes 启用后只接受 `Authorization: Bearer <DEBUG_DASHBOARD_TOKEN>`。
- Query token 继续拒绝。

覆盖测试：

- `test_debug_routes_when_enabled_require_header_token`

## 测试结果

```bash
./scripts/test_security_gate.sh
# passed, 16 tests

cd backend
uv run --extra dev pytest app/tests/test_admin_debug_security.py app/tests/test_admin_console.py app/tests/test_test_scripts.py app/tests/test_health_readiness.py -q -rx
# passed, 18 tests
```

待最终收口命令：

```bash
./scripts/test_unit.sh
# passed, 22 tests

./scripts/test_security_gate.sh
# passed, 16 tests

uv run --extra dev ruff check app tests
# All checks passed

uv run --extra dev pytest -q -rx
# passed

uv run alembic heads && uv run alembic current
# 0007_agent_prompt_configs (head)
```

Docker daemon 当前未启动；`./scripts/test.sh` 已验证会明确提示：

```text
Docker daemon is not running; start Docker to run integration tests
```
