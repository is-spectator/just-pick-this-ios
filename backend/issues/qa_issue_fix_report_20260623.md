# QA Issue Fix Report 2026-06-23

Source report:
`outputs/qa_issue_report_20260623/pipii_system_test_issues_20260623.xlsx`

## Summary

This pass fixed or bounded the seven issues found during the QA/system test run:

| Issue | Status | Fix |
| --- | --- | --- |
| ISS-001 `/v1/chat/turn` leaks DB `OperationalError` | Fixed | Added FastAPI exception handlers for SQLAlchemy/database config failures and a regression test. No-DB chat now returns structured `503` with `detail.code=database_unavailable`. |
| ISS-002 full pytest fails hard without local Postgres | Fixed | Added pytest collection DB readiness detection. DB integration tests skip with a clear reason when `DATABASE_URL` is unreachable; `--require-db` still fails fast for CI/release checks. |
| ISS-003 product benchmark fails with raw DB stack | Fixed | `scripts/run_product_benchmark.py` now checks DB readiness before starting product turns and writes blocked `product_benchmark_summary.*` plus an empty `results.jsonl` when DB is unavailable. |
| ISS-004 `alembic current` raw DB stack | Mitigated | Added `scripts/check_db_ready.sh` and README guidance: run it before `alembic current`. `alembic heads` remains DB-free; `current` still requires a real DB by design. |
| ISS-005 missing `ADMIN_TOKEN` returns 503 | Fixed | Admin/Ops auth now returns `401 admin token required` before DB access even when token config is missing. |
| ISS-006 iOS build by simulator name fails | Fixed | Added `scripts/build_ios_sim.sh`; it resolves a concrete simulator destination id and builds using `-destination id=...`. Verified with `BUILD SUCCEEDED`. |
| ISS-007 Docker daemon missing blocks full integration | Documented | Existing `scripts/test.sh` already fails early with a clear Docker message. README now distinguishes no-DB checks from full integration checks. |

## Verification

Commands run:

```sh
cd backend
uv run --extra dev pytest app/tests/test_database_unavailable_response.py \
  app/tests/test_admin_debug_security.py \
  app/tests/test_product_benchmark_readiness.py \
  app/tests/test_test_scripts.py -q -rx
# 12 passed

uv run --extra dev pytest -q -rx
# passed with DB integration tests skipped because local Postgres is unreachable

uv run --extra dev ruff check app tests ../scripts/run_product_benchmark.py
# passed

uv run --extra dev alembic heads
# 0012_email_auth (head)

uv run --extra dev alembic current
# blocked by local Postgres being unreachable

./scripts/test_security_gate.sh
# 20 passed

./scripts/test_unit.sh
# 31 passed

./scripts/test.sh
# blocked: Docker daemon is not running

./scripts/check_db_ready.sh
# blocked with clear database-unreachable message

uv run python ../scripts/run_product_benchmark.py \
  --benchmark ../benchmarks/pipi_onsite_500_v1.json \
  --out /tmp/pipi-product-benchmark-db-blocked \
  --limit 1 \
  --no-reports
# wrote blocked product_benchmark_summary.json

./scripts/build_ios_sim.sh
# BUILD SUCCEEDED
```

## Notes

- Product-path DB tests are intentionally skipped in local no-DB mode. Run `./scripts/test.sh` with Docker/PostgreSQL for the full integration path.
- `alembic current` cannot be made DB-free because it reads the current migration state from the database. The new `scripts/check_db_ready.sh` provides the missing preflight and operator message.
