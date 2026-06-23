# Stability Launch Report 2026-06-01

## 结论

本轮按上线阻塞清单做了后端稳定性硬化，没有新增产品能力、没有改移动端、没有接真实 LLM。

## 已处理

- Debug routes 默认不挂载，启用后必须使用 `Authorization: Bearer <DEBUG_DASHBOARD_TOKEN>` 或 `x-debug-token`，缺 token 返回 503。
- Admin routes 拒绝 `?token=` 和 `x-admin-token`，只接受 `Authorization: Bearer <ADMIN_TOKEN>`。
- 请求期自动 seed 默认关闭，生产/预发禁止 `AUTO_SEED_ON_REQUEST=true`。
- `/v1/chat/turn` 和 bootstrap 路径默认要求 `device_uid`，缺失返回 400；传 conversation_id 时校验设备归属，跨设备返回 403。
- 新增 `/health/live` 和 `/health/ready`；ready 检查数据库连通、Alembic current/head、checkpoint 配置状态。
- 生产/预发配置 guard：要求 admin token、database url，禁止 eval bypass、eval mode、mock shadow provider，checkpoint required 时必须 postgres backend。
- Pipi request middleware 已安装，响应带 `x-request-id`，结构化日志包含 request/runtime/intent/latency/tool/error 关键信息。
- `PipiLoop` trace 补齐 input gate、context pack、reasoner、tool、evaluator、answer gate，并记录 loop/tool latency。
- `scripts/test.sh` 增加 Docker 命令和 daemon 检查；新增 seed/migrate/ready/prod 启动脚本。
- 新增 GitHub Actions backend CI，使用 Postgres service 跑 migration、pytest、ruff。
- Review 打包忽略 `build/`、`.codegraph/`、`.understand-anything/`、`xcuserdata/`，避免把本地索引和 DerivedData 塞进 zip。

## Zip 体积来源

上次 37M review zip 的主要嫌疑不是业务代码，而是本地生成物：

- `build/`: 181M，Xcode DerivedData / ModuleCache。
- `backend/.venv`: 126M，Python 虚拟环境。
- `backend-node-legacy/node_modules`: 324M，Node 依赖。
- `.codegraph`: 7.9M，codegraph 索引数据库。

这些都不应该进入 review 包。

## 验证

```bash
cd backend
uv run --extra dev pytest -q -rx
uv run --extra dev ruff check app tests
uv run alembic heads
uv run alembic current
```

结果：

- `pytest`: 通过，344 tests collected。
- `ruff`: All checks passed。
- `alembic heads/current`: `0007_agent_prompt_configs (head)`。
- `scripts/test_unit.sh`: 22 passed。
- `scripts/test.sh`: Docker daemon 未启动时会明确报错并退出。

## 注意

- `LANGGRAPH_CHECKPOINT_BACKEND` 默认是 `disabled`，避免开发/测试默认 MemorySaver 序列化 DB-backed runtime 对象；生产如果设置 `LANGGRAPH_CHECKPOINT_REQUIRED=true`，必须配置 postgres checkpoint backend，否则启动失败。
- Debug routes 现在默认不可用，测试或本地排查要显式设置 `ENABLE_DEBUG_ROUTES=true` 和 `DEBUG_DASHBOARD_TOKEN`。
- Admin 访问方式改为 Bearer token；URL query token 已废弃并拒绝。
