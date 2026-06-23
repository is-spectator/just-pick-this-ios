from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from app.agent.schemas import (
    REASONER_DECISION_SCHEMA_NAME,
    REASONER_DECISION_SCHEMA_VERSION,
    ReasonerDecision,
    reasoner_decision_json_schema,
)
from app.config import get_settings


ShadowReasonerStatus = Literal[
    "disabled",
    "success",
    "schema_error",
    "provider_error",
    "timeout",
]
ShadowRawMode = Literal["structured_output", "json_object_fallback", "mock"]


class ShadowReasonerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    provider: str
    model: str
    status: ShadowReasonerStatus
    decision_json: dict[str, Any] | None = None
    normalized_decision: dict[str, Any] | None = None
    error: str | None = None
    latency_ms: float
    schema_enforced: bool = False
    schema_name: str | None = REASONER_DECISION_SCHEMA_NAME
    schema_version: str = REASONER_DECISION_SCHEMA_VERSION
    raw_mode: ShadowRawMode = "mock"
    why_different_from_deterministic: str | None = None
    risk_if_promoted: str | None = None
    confidence: float | None = None


class ShadowReasoner:
    """LLM shadow-mode reasoner that validates decisions without side effects."""

    @property
    def provider(self) -> str:
        return str(getattr(get_settings(), "llm_provider", "none") or "none")

    @property
    def model(self) -> str:
        return str(getattr(get_settings(), "llm_model", "none") or "none")

    async def run_shadow(
        self,
        context_pack: dict[str, Any],
        deterministic_decision: Any,
    ) -> ShadowReasonerResult:
        settings = get_settings()
        provider = str(getattr(settings, "llm_provider", "none") or "none")
        model = str(getattr(settings, "llm_model", "none") or "none")
        started_at = time.perf_counter()

        disabled_reason = _disabled_reason(settings=settings, provider=provider)
        if disabled_reason is not None:
            return _result(
                enabled=False,
                provider=provider,
                model=model,
                status="disabled",
                error=disabled_reason,
                started_at=started_at,
                raw_mode=_raw_mode_for_provider(provider),
            )

        provider_response: dict[str, Any] | None = None
        try:
            provider_response = await asyncio.wait_for(
                self._call_provider(
                    provider=provider,
                    model=model,
                    context_pack=context_pack,
                    deterministic_decision=deterministic_decision,
                ),
                timeout=float(getattr(settings, "llm_timeout_seconds", 10.0) or 10.0),
            )
        except TimeoutError:
            return _result(
                enabled=True,
                provider=provider,
                model=model,
                status="timeout",
                error="Shadow provider timed out.",
                started_at=started_at,
                raw_mode=_raw_mode_for_provider(provider),
            )
        except Exception as exc:
            return _result(
                enabled=True,
                provider=provider,
                model=model,
                status="provider_error",
                error=str(exc) or exc.__class__.__name__,
                started_at=started_at,
                raw_mode=_raw_mode_for_provider(provider),
            )

        raw_mode = str(provider_response.get("raw_mode") or _raw_mode_for_provider(provider))
        schema_enforced = bool(provider_response.get("schema_enforced"))
        raw_decision = provider_response.get("payload")
        try:
            decision_json = _coerce_decision_json(raw_decision)
            normalized_decision = validate_shadow_decision_schema(decision_json)
        except (TypeError, ValueError, json.JSONDecodeError, ValidationError) as exc:
            return _result(
                enabled=True,
                provider=provider,
                model=model,
                status="schema_error",
                decision_json=raw_decision if isinstance(raw_decision, dict) else None,
                error=_format_schema_error(exc),
                started_at=started_at,
                schema_enforced=schema_enforced,
                raw_mode=_safe_raw_mode(raw_mode),
            )

        return _result(
            enabled=True,
            provider=provider,
            model=model,
            status="success",
            decision_json=decision_json,
            normalized_decision=normalized_decision,
            started_at=started_at,
            schema_enforced=schema_enforced,
            raw_mode=_safe_raw_mode(raw_mode),
            **_shadow_audit_metadata(deterministic_decision, normalized_decision),
        )

    async def _call_provider(
        self,
        *,
        provider: str,
        model: str,
        context_pack: dict[str, Any],
        deterministic_decision: Any,
    ) -> dict[str, Any]:
        if provider == "mock_shadow":
            return _provider_result(
                _mock_shadow_decision(deterministic_decision),
                raw_mode="mock",
                schema_enforced=True,
            )
        if provider == "mock_shadow_schema_error":
            return _provider_result(
                {
                    "type": "tool",
                    "tool_args": {},
                    "reason": "Invalid shadow decision for schema-error tests.",
                },
                raw_mode="mock",
                schema_enforced=True,
            )
        if provider == "openai":
            return await _call_openai_shadow(
                model=model,
                context_pack=context_pack,
                deterministic_decision=deterministic_decision,
            )
        raise RuntimeError(f"Unsupported shadow LLM provider: {provider}")


_REASONER_DECISION_ADAPTER = TypeAdapter(ReasonerDecision)


def build_reasoner_decision_json_schema() -> dict[str, Any]:
    return {
        "name": REASONER_DECISION_SCHEMA_NAME,
        "strict": True,
        "schema": reasoner_decision_json_schema(strict=True),
    }


def validate_shadow_decision_schema(decision_json: dict[str, Any]) -> dict[str, Any]:
    _reject_extra_shadow_keys(decision_json)
    decision = _REASONER_DECISION_ADAPTER.validate_python(decision_json)
    return decision.model_dump(mode="json")


def _disabled_reason(*, settings: Any, provider: str) -> str | None:
    if not bool(getattr(settings, "llm_shadow_enabled", False)):
        return "LLM shadow mode is disabled."
    if provider == "none":
        return "LLM shadow provider is none."
    if _provider_requires_api_key(provider) and getattr(settings, "openai_api_key", None) is None:
        return "LLM shadow provider is missing an API key."
    return None


def _provider_requires_api_key(provider: str) -> bool:
    return provider not in {"mock_shadow", "mock_shadow_schema_error", "none"}


async def _call_openai_shadow(
    *,
    model: str,
    context_pack: dict[str, Any],
    deterministic_decision: Any,
) -> dict[str, Any]:
    settings = get_settings()
    api_key = getattr(settings, "openai_api_key", None)
    if api_key is None:
        raise RuntimeError("OpenAI API key is missing.")

    model_name = model if model and model != "none" else str(getattr(settings, "openai_model", "gpt-4.1-mini"))
    base_url = str(getattr(settings, "openai_base_url", "https://api.openai.com/v1")).rstrip("/")
    timeout_seconds = float(getattr(settings, "llm_timeout_seconds", 10.0) or 10.0)
    base_payload = {
        "model": model_name,
        "temperature": 0,
        "messages": _openai_shadow_messages(
            context_pack=context_pack,
            deterministic_decision=deterministic_decision,
        ),
    }
    headers = {
        "Authorization": f"Bearer {api_key.get_secret_value()}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json={
                **base_payload,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": build_reasoner_decision_json_schema(),
                },
            },
        )
        raw_mode: ShadowRawMode = "structured_output"
        schema_enforced = True
        if response.status_code >= 400 and _should_fallback_to_json_object(response):
            response = await client.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json={**base_payload, "response_format": {"type": "json_object"}},
            )
            raw_mode = "json_object_fallback"
            schema_enforced = False

    if response.status_code >= 400:
        raise RuntimeError(f"OpenAI shadow request failed with HTTP {response.status_code}: {_safe_response_text(response)}")

    data = response.json()
    content = _extract_openai_content(data)
    if content is None:
        raise RuntimeError("OpenAI shadow response did not include message content.")
    return _provider_result(content, raw_mode=raw_mode, schema_enforced=schema_enforced)


def _openai_shadow_messages(
    *,
    context_pack: dict[str, Any],
    deterministic_decision: Any,
) -> list[dict[str, str]]:
    task_payload = {
        "context_pack": _redact_and_shrink(context_pack),
        "deterministic_decision": _redact_and_shrink(_dump_decision(deterministic_decision)),
    }
    return [
        {
            "role": "system",
            "content": (
                "你是皮皮 Agent 的 shadow reasoner。你只做影子判断，不执行工具，不创建卡片，"
                "不影响线上答案。必须只输出符合 ReasonerDecision schema 的 JSON object。"
                "推荐卡和求一个只能通过 tool_name 表达，不要直接输出卡片 JSON。"
                "这是 audit-only：不能调用 AbilityCenter，不能写 RecommendationCard/HelpCard，不能改变 product output。"
                "请在 reason 或 message 中覆盖 why_different_from_deterministic、risk_if_promoted、confidence 三点；"
                "不要新增 schema 外字段。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(task_payload, ensure_ascii=False, separators=(",", ":")),
        },
    ]


def _dump_decision(deterministic_decision: Any) -> dict[str, Any]:
    if hasattr(deterministic_decision, "model_dump"):
        return deterministic_decision.model_dump(mode="json")
    if isinstance(deterministic_decision, dict):
        return dict(deterministic_decision)
    return {}


def _redact_and_shrink(value: Any, *, max_chars: int = 12000) -> Any:
    redacted = _redact_secretish_values(value)
    try:
        encoded = json.dumps(redacted, ensure_ascii=False, default=str)
    except TypeError:
        encoded = json.dumps(str(redacted), ensure_ascii=False)
    if len(encoded) <= max_chars:
        return redacted
    return {
        "truncated": True,
        "preview": encoded[:max_chars],
    }


def _redact_secretish_values(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(marker in key_text for marker in ("api_key", "token", "authorization", "password", "secret")):
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = _redact_secretish_values(item)
        return redacted
    if isinstance(value, list):
        return [_redact_secretish_values(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_secretish_values(item) for item in value]
    return value


def _extract_openai_content(data: dict[str, Any]) -> str | None:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "\n".join(parts) if parts else None
    return None


def _provider_result(
    payload: dict[str, Any] | str,
    *,
    raw_mode: ShadowRawMode,
    schema_enforced: bool,
) -> dict[str, Any]:
    return {
        "payload": payload,
        "raw_mode": raw_mode,
        "schema_enforced": bool(schema_enforced),
    }


def _raw_mode_for_provider(provider: str) -> ShadowRawMode:
    if provider.startswith("mock_"):
        return "mock"
    return "json_object_fallback"


def _safe_raw_mode(value: str) -> ShadowRawMode:
    if value in {"structured_output", "json_object_fallback", "mock"}:
        return value  # type: ignore[return-value]
    return "json_object_fallback"


def _should_fallback_to_json_object(response: httpx.Response) -> bool:
    if response.status_code not in {400, 404, 422}:
        return False
    text = _safe_response_text(response).lower()
    markers = ("json_schema", "response_format", "unsupported", "not supported")
    return any(marker in text for marker in markers)


def _safe_response_text(response: httpx.Response) -> str:
    return response.text.replace("\n", " ")[:500]


def _mock_shadow_decision(deterministic_decision: Any) -> dict[str, Any]:
    if hasattr(deterministic_decision, "model_dump"):
        candidate = deterministic_decision.model_dump(mode="json")
    elif isinstance(deterministic_decision, dict):
        candidate = dict(deterministic_decision)
    else:
        candidate = {}

    try:
        normalized = validate_shadow_decision_schema(candidate)
        if normalized.get("type") == "tool" and normalized.get("tool_name") == "draft_help_card":
            return {
                "type": "tool",
                "tool_name": "create_recommendation_card",
                "tool_args": {
                    "evidence_ids": ["shadow_mock_evidence"],
                    "item": {"title": "Shadow mock recommendation"},
                    "decision_factor": {"text": "Shadow mock would try a card."},
                },
                "reason": "Mock shadow intentionally differs on help-card drafts for comparison tests.",
            }
        return normalized
    except (ValueError, ValidationError):
        pass

    return {
        "type": "answer",
        "message": "Shadow mock mirrors deterministic mode.",
        "ui_events": [],
        "data": {},
    }


def _coerce_decision_json(raw_decision: Any) -> dict[str, Any]:
    if isinstance(raw_decision, str):
        raw_decision = json.loads(raw_decision)
    if not isinstance(raw_decision, dict):
        raise TypeError("Shadow provider returned a non-object decision.")
    return raw_decision


def _reject_extra_shadow_keys(value: dict[str, Any]) -> None:
    decision_type = value.get("type")
    if decision_type == "tool":
        allowed = {"type", "tool_name", "tool_args", "reason"}
    elif decision_type == "answer":
        allowed = {"type", "message", "ui_events", "data"}
    else:
        allowed = {"type"}
    extras = set(value) - allowed
    if extras:
        raise ValueError(f"Unexpected shadow decision fields: {sorted(extras)}")


def _format_schema_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(error["msg"] for error in exc.errors())[:500]
    return str(exc)[:500]


def _result(
    *,
    enabled: bool,
    provider: str,
    model: str,
    status: ShadowReasonerStatus,
    started_at: float,
    decision_json: dict[str, Any] | None = None,
    normalized_decision: dict[str, Any] | None = None,
    error: str | None = None,
    schema_enforced: bool = False,
    raw_mode: ShadowRawMode = "mock",
    why_different_from_deterministic: str | None = None,
    risk_if_promoted: str | None = None,
    confidence: float | None = None,
) -> ShadowReasonerResult:
    return ShadowReasonerResult(
        enabled=enabled,
        provider=provider,
        model=model,
        status=status,
        decision_json=decision_json,
        normalized_decision=normalized_decision,
        error=error,
        latency_ms=round((time.perf_counter() - started_at) * 1000, 3),
        schema_enforced=schema_enforced,
        schema_name=REASONER_DECISION_SCHEMA_NAME,
        schema_version=REASONER_DECISION_SCHEMA_VERSION,
        raw_mode=raw_mode,
        why_different_from_deterministic=why_different_from_deterministic,
        risk_if_promoted=risk_if_promoted,
        confidence=confidence,
    )


def _shadow_audit_metadata(
    deterministic_decision: Any,
    normalized_decision: dict[str, Any],
) -> dict[str, Any]:
    deterministic = _dump_decision(deterministic_decision)
    mismatch = deterministic != normalized_decision
    return {
        "why_different_from_deterministic": (
            "Shadow decision differs from deterministic decision for offline comparison."
            if mismatch
            else "Shadow decision matches deterministic decision."
        ),
        "risk_if_promoted": (
            "Do not promote without evaluator and trace review; shadow cannot validate evidence side effects."
            if mismatch
            else "Low risk observed in shadow because the decision matches deterministic output."
        ),
        "confidence": 0.65 if mismatch else 0.9,
    }


__all__ = [
    "ShadowReasoner",
    "ShadowReasonerResult",
    "ShadowReasonerStatus",
    "build_reasoner_decision_json_schema",
    "validate_shadow_decision_schema",
]
