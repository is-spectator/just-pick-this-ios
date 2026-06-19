"""Health check schema."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    ok: Literal[True]
    service: str
    version: str
    env: str
    eval_mode: bool
