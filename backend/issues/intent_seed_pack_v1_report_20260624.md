# Intent Seed Pack V1 Report 2026-06-24

## Issue

ISS-016: 上线首批高价值 `IntentAnswer` 种子包。此前 `seed_service`
只包含 3 条硬编码种子，无法覆盖 500-case benchmark 中的高频区域餐饮、
店内点单、旅行逛街和家庭/约会/不辣等 profile 场景。

## Changes

- Added `backend/app/data/intent_seed_pack_v1.json`.
- The pack contains 100 active approved `IntentAnswer` rows:
  - 20 high-frequency scenes;
  - 5 variants per scene: stable, parents, solo, date, non_spicy;
  - coverage across `restaurant`, `ordering_bundle`, and `place`;
  - coverage across `in_area` and `in_venue`.
- Updated `seed_service` to load the pack idempotently with deterministic UUIDs.
- Updated runtime seed guard so existing databases with only the legacy 3 seeds
  will automatically receive the v1 pack on the next seed check.

## Safety

- Existing legacy seed IDs are unchanged.
- Seed pack rows use `source_type=curated_seed_pack_v1` and deterministic
  `source_ref_id=seed-pack-v1:{intent_key}`.
- Images are optional. Seed rows do not attach unverifiable image URLs.
- Each row carries `evidence_json.approved=true`, target type, location state,
  constraints, and a single decision factor.

## Verification

Added `app/tests/test_seed_pack_v1.py`:

- validates at least 100 rows;
- validates at least 20 city/place scenes;
- validates required card/evidence fields;
- validates deterministic active approved `IntentAnswer` row conversion.

Executed locally:

```bash
cd backend
uv run --extra dev pytest app/tests/test_seed_pack_v1.py -q -rx
uv run --extra dev pytest app/tests -q -rx
uv run --extra dev ruff check app tests ../scripts/run_product_benchmark.py
uv run alembic heads
```

All commands above passed. `uv run alembic current` was attempted and failed
locally because PostgreSQL on the developer machine requires a password:
`fe_sendauth: no password supplied`.
