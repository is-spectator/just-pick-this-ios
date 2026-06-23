#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"

cd "$BACKEND_DIR"

unset DATABASE_URL
uv sync --extra dev
uv run --extra dev pytest \
  app/tests/test_production_config_guard.py \
  app/tests/test_admin_debug_security.py \
  app/tests/test_checkpoint_runtime_guard.py \
  -q -rx
