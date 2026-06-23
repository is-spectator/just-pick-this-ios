#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required for integration tests" >&2
  exit 127
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not running; start Docker to run integration tests" >&2
  exit 127
fi

cd "$BACKEND_DIR"

uv sync --extra dev
docker compose up -d postgres
trap 'docker compose stop postgres >/dev/null 2>&1 || true' EXIT

until docker compose exec -T postgres pg_isready -U just_pick_this -d just_pick_this_agent_v0 >/dev/null 2>&1; do
  sleep 1
done

export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://just_pick_this:just_pick_this@localhost:5432/just_pick_this_agent_v0}"

uv run --extra dev alembic upgrade head
uv run --extra dev pytest -q -rx
uv run --extra dev ruff check app tests
