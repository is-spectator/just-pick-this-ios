#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"

uv run python - <<'PY'
from __future__ import annotations

import sys

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings

settings = get_settings()
if settings.database_url is None:
    print("DATABASE_URL is not configured.", file=sys.stderr)
    sys.exit(1)

engine = None
try:
    engine = create_engine(str(settings.database_url), pool_pre_ping=True)
    with engine.connect() as connection:
        connection.execute(text("select 1"))
except (SQLAlchemyError, OSError) as exc:
    print(
        "DATABASE_URL is configured but unreachable. "
        "Start Postgres/Docker or run ./scripts/test.sh for managed integration tests. "
        f"({exc.__class__.__name__})",
        file=sys.stderr,
    )
    sys.exit(1)
finally:
    if engine is not None:
        engine.dispose()

print("database ready")
PY
