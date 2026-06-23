from __future__ import annotations

import time
from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from app.ops.prompt_service import DEFAULT_ENVIRONMENT, active_prompt_version_map, active_version


_CACHE: dict[str, tuple[float, dict[str, dict[str, Any]]]] = {}
_TTL_SECONDS = 5.0


class PromptRegistry:
    def __init__(self, session: Session, *, environment: str = DEFAULT_ENVIRONMENT) -> None:
        self.session = session
        self.environment = environment

    def load_active_pack(self) -> dict[str, dict[str, Any]]:
        now = time.monotonic()
        cached = _CACHE.get(self.environment)
        if cached is not None:
            expires_at, value = cached
            if expires_at > now:
                return deepcopy(value)
        value = active_prompt_version_map(self.session, environment=self.environment)
        _CACHE[self.environment] = (now + _TTL_SECONDS, deepcopy(value))
        return value

    def get_prompt(self, prompt_key: str) -> dict[str, Any]:
        version = active_version(self.session, prompt_key, environment=self.environment)
        return {
            "prompt_key": prompt_key,
            "version_id": str(version.id),
            "version": version.version,
            "checksum": version.checksum,
            "content": version.content,
            "status": version.status,
        }

    @staticmethod
    def invalidate(environment: str | None = None) -> None:
        if environment is None:
            _CACHE.clear()
        else:
            _CACHE.pop(environment, None)
