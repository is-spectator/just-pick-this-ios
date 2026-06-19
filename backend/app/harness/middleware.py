from __future__ import annotations

import json
import logging
from time import perf_counter
from typing import Any, Awaitable, Callable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


ASGIReceive = Callable[[], Awaitable[dict[str, Any]]]
ASGISend = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[dict[str, Any], ASGIReceive, ASGISend], Awaitable[None]]


class HarnessRequestContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    request_id: str = Field(default_factory=lambda: str(uuid4()))
    runtime: str = "hybrid_harness"
    events: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def record_event(self, event: dict[str, Any]) -> None:
        self.events.append(dict(event))


class HybridHarnessMiddleware:
    """Tiny ASGI hook that gives requests a place to carry harness metadata."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        state_key: str = "pipi_harness",
        response_header: str = "x-pipi-runtime",
        response_header_value: str = "hybrid-harness",
    ) -> None:
        self.app = app
        self.state_key = state_key
        self.response_header = response_header.lower().encode("latin-1")
        self.response_header_value = response_header_value.encode("latin-1")
        self.logger = logging.getLogger("pipi.request")

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: ASGIReceive,
        send: ASGISend,
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        state = scope.setdefault("state", {})
        request_id = _request_id_from_scope(scope) or str(uuid4())
        if isinstance(state, dict):
            state.setdefault(self.state_key, HarnessRequestContext(request_id=request_id))
            state["request_id"] = request_id
        started = perf_counter()
        status_code = 500

        async def send_with_harness_header(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status") or 500)
                headers = list(message.get("headers") or [])
                if not any(key.lower() == self.response_header for key, _ in headers):
                    headers.append((self.response_header, self.response_header_value))
                if not any(key.lower() == b"x-request-id" for key, _ in headers):
                    headers.append((b"x-request-id", request_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        error_type: str | None = None
        try:
            await self.app(scope, receive, send_with_harness_header)
        except Exception as exc:
            error_type = exc.__class__.__name__
            raise
        finally:
            self.logger.info(
                "pipi_request",
                extra={
                    "pipi_log": {
                        "request_id": request_id,
                        "path": scope.get("path"),
                        "method": scope.get("method"),
                        "status_code": status_code,
                        "latency_ms": round((perf_counter() - started) * 1000, 2),
                        "conversation_id": _state_value(state, "conversation_id"),
                        "agent_run_id": _state_value(state, "agent_run_id"),
                        "runtime_path": _state_value(state, "runtime_path"),
                        "intent_type": _state_value(state, "intent_type"),
                        "tool_call_count": _state_value(state, "tool_call_count", 0),
                        "error_type": error_type,
                    }
                },
            )


HarnessMiddleware = HybridHarnessMiddleware
PipiHarnessMiddleware = HybridHarnessMiddleware
HybridHarnessRequestContext = HarnessRequestContext
PipiHarnessRequestContext = HarnessRequestContext


def install_hybrid_harness_middleware(app: Any) -> Any:
    add_middleware = getattr(app, "add_middleware", None)
    if add_middleware is None:
        raise TypeError("app must expose add_middleware")
    add_middleware(HybridHarnessMiddleware)
    return app


def _request_id_from_scope(scope: dict[str, Any]) -> str | None:
    for key, value in scope.get("headers") or []:
        if key.lower() == b"x-request-id":
            try:
                request_id = value.decode("latin-1").strip()
            except Exception:
                return None
            return request_id or None
    return None


def _state_value(state: Any, key: str, default: Any = None) -> Any:
    if isinstance(state, dict):
        harness = state.get("pipi_harness")
        if isinstance(harness, HarnessRequestContext):
            return harness.metadata.get(key, default)
    return default


class JsonPipiLogFormatter(logging.Formatter):
    """Small JSON formatter for request logs without leaking headers/secrets."""

    def format(self, record: logging.LogRecord) -> str:
        payload = getattr(record, "pipi_log", None)
        if isinstance(payload, dict):
            return json.dumps(payload, ensure_ascii=False, default=str)
        return super().format(record)


__all__ = [
    "HarnessMiddleware",
    "HarnessRequestContext",
    "HybridHarnessRequestContext",
    "HybridHarnessMiddleware",
    "PipiHarnessMiddleware",
    "PipiHarnessRequestContext",
    "install_hybrid_harness_middleware",
]
