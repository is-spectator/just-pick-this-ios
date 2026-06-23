#!/usr/bin/env python3
"""CLI wrapper for pipi quality gate reports."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.eval.quality_gate import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
