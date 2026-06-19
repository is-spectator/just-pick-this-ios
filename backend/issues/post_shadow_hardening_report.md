# Post Shadow Hardening Report

## Conclusion

P0/P1 hardening is complete for this round.

## Completed

- Added reproducible test scripts:
  - `scripts/test.sh`
  - `scripts/test_unit.sh`
- Deleted legacy `backend-node-legacy/.env`.
- Hardened `.gitignore` for environment files while preserving `.env.example`.
- Added secret-scan and script-executable tests.
- Exported strict `ReasonerDecision` JSON schema.
- Updated shadow OpenAI flow to try `json_schema` first and explicitly mark `json_object_fallback`.
- Added `schema_enforced`, `schema_name`, `schema_version`, and `raw_mode` to shadow trace payloads.
- Added benchmark coverage-only mode and non-empty results guard.
- Added shadow quality-diff heuristics and unsafe shadow counts.
- Exposed shadow summary and decision diffs on admin trace detail and trace list.

## Verification

```bash
uv run --extra dev pytest -q -rx
uv run --extra dev ruff check app tests
uv run --extra dev python -m alembic heads
uv run --extra dev python -m alembic current
uv run --extra dev python ../scripts/benchmark_quality_report.py --benchmark ../benchmarks/pipi_onsite_500_v1.json --out /tmp/pipi-post-shadow-hardening
```

## Results

- `pytest`: passed.
- `ruff`: passed.
- `python -m alembic heads`: `0007_agent_prompt_configs (head)`.
- `python -m alembic current`: `0007_agent_prompt_configs (head)`.
- Benchmark coverage-only report generated with:
  - `report_mode=coverage_only`
  - `evaluated_case_count=0`
  - `benchmark_case_count=500`
  - explicit “No product runtime results were evaluated” text.

## Notes

- `uv run alembic heads/current` was SIGKILLed by the local process environment, but `uv run --extra dev python -m alembic heads/current` completed successfully.
- `backend/.env` remains a local ignored file and is not part of repository/zip output. The removed leak was `backend-node-legacy/.env`.
