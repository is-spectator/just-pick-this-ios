#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
WEB_CONCURRENCY="${WEB_CONCURRENCY:-1}"

cd "$BACKEND_DIR"
exec uv run uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}" --workers "$WEB_CONCURRENCY"
