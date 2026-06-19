from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import get_settings
from app.services.query_rewrite import QueryRewriteResult, rewrite_query


LlmRewriteStatus = Literal[
    "disabled",
    "success",
    "schema_error",
    "provider_error",
    "timeout",
    "low_confidence",
]


class LlmQueryRewritePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_query: str
    extracted_slots: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    notes: list[str] = Field(default_factory=list)


class LlmQueryRewriteResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    provider: str
    model: str
    status: LlmRewriteStatus
    original_query: str
    canonical_query: str | None = None
    extracted_slots: dict[str, Any] = Field(default_factory=dict)
    rewrite_confidence: float | None = None
    notes: list[str] = Field(default_factory=list)
    accepted: bool = False
    selected_method: str = "deterministic"
    merged_canonical_query: str | None = None
    merged_slots: dict[str, Any] = Field(default_factory=dict)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    latency_ms: float = 0.0


async def build_llm_query_rewrite(
    message: str,
    *,
    deterministic: QueryRewriteResult | None = None,
) -> LlmQueryRewriteResult:
    """Return an LLM query-rewrite suggestion without changing product state."""

    settings = get_settings()
    provider = str(getattr(settings, "llm_provider", "none") or "none")
    model = str(getattr(settings, "llm_model", "none") or "none")
    original = str(message or "").strip()
    deterministic = deterministic or rewrite_query(original)
    started = time.perf_counter()

    disabled = _disabled_reason(settings=settings, provider=provider)
    if disabled is not None:
        return _result(
            enabled=False,
            provider=provider,
            model=model,
            status="disabled",
            original_query=original,
            error=disabled,
            started=started,
        )

    try:
        payload = await asyncio.wait_for(
            _call_provider(provider=provider, model=model, message=original, deterministic=deterministic),
            timeout=float(getattr(settings, "llm_timeout_seconds", 10.0) or 10.0),
        )
    except TimeoutError:
        return _result(
            enabled=True,
            provider=provider,
            model=model,
            status="timeout",
            original_query=original,
            error="LLM rewrite provider timed out.",
            started=started,
        )
    except Exception as exc:
        return _result(
            enabled=True,
            provider=provider,
            model=model,
            status="provider_error",
            original_query=original,
            error=str(exc) or exc.__class__.__name__,
            started=started,
        )

    try:
        parsed = LlmQueryRewritePayload.model_validate(payload)
    except ValidationError as exc:
        return _result(
            enabled=True,
            provider=provider,
            model=model,
            status="schema_error",
            original_query=original,
            error=_format_validation_error(exc),
            started=started,
        )

    return _result(
        enabled=True,
        provider=provider,
        model=model,
        status="success",
        original_query=original,
        canonical_query=parsed.canonical_query,
        extracted_slots=_clean_slots(parsed.extracted_slots),
        rewrite_confidence=parsed.confidence,
        notes=parsed.notes,
        started=started,
    )


def select_query_rewrite(
    deterministic: QueryRewriteResult,
    llm_result: LlmQueryRewriteResult | None,
    *,
    min_confidence: float | None = None,
) -> tuple[QueryRewriteResult, LlmQueryRewriteResult | None]:
    """Safely merge LLM rewrite slots into deterministic rewrite.

    Existing deterministic slots always win. LLM rewrite can only add missing
    slots, so final tool/routing decisions remain deterministic InputGate
    decisions over the merged structured context.
    """

    if llm_result is None:
        return deterministic, None

    settings = get_settings()
    threshold = float(
        min_confidence
        if min_confidence is not None
        else getattr(settings, "llm_rewrite_min_confidence", 0.78)
    )
    if not llm_result.enabled or llm_result.status != "success":
        return deterministic, llm_result.model_copy(
            update={
                "accepted": False,
                "selected_method": "deterministic",
                "merged_canonical_query": deterministic.canonical_query,
                "merged_slots": dict(deterministic.extracted_slots),
            }
        )

    confidence = float(llm_result.rewrite_confidence or 0.0)
    if confidence < threshold:
        return deterministic, llm_result.model_copy(
            update={
                "status": "low_confidence",
                "accepted": False,
                "selected_method": "deterministic",
                "merged_canonical_query": deterministic.canonical_query,
                "merged_slots": dict(deterministic.extracted_slots),
                "error": f"rewrite_confidence {confidence} < threshold {threshold}",
            }
        )

    merged = dict(deterministic.extracted_slots)
    conflicts: list[dict[str, Any]] = []
    added = False
    for key, value in llm_result.extracted_slots.items():
        if _is_empty_slot(value):
            continue
        existing = merged.get(key)
        if _is_empty_slot(existing):
            merged[key] = value
            added = True
            continue
        if existing != value:
            conflicts.append({"slot": key, "deterministic": existing, "llm": value})

    canonical = _canonical_query_from_slots(
        original=deterministic.original_query,
        fallback=llm_result.canonical_query or deterministic.canonical_query,
        slots=merged,
    )
    selected = QueryRewriteResult(
        original_query=deterministic.original_query,
        canonical_query=canonical,
        extracted_slots=merged,
        confidence=max(float(deterministic.confidence), confidence if added else float(deterministic.confidence)),
        notes=[
            *deterministic.notes,
            "LLM rewrite merged into missing slots." if added else "LLM rewrite produced no usable new slots.",
            *llm_result.notes,
        ],
    )
    return selected, llm_result.model_copy(
        update={
            "accepted": added,
            "selected_method": "llm_merged" if added else "deterministic",
            "merged_canonical_query": canonical,
            "merged_slots": merged,
            "conflicts": conflicts,
        }
    )


def _disabled_reason(*, settings: Any, provider: str) -> str | None:
    if not bool(getattr(settings, "llm_rewrite_enabled", False)):
        return "LLM query rewrite is disabled."
    if provider == "none":
        return "LLM provider is none."
    if provider == "openai" and getattr(settings, "openai_api_key", None) is None:
        return "OpenAI API key is missing."
    return None


async def _call_provider(
    *,
    provider: str,
    model: str,
    message: str,
    deterministic: QueryRewriteResult,
) -> dict[str, Any]:
    if provider == "mock_shadow":
        return _mock_rewrite_payload(message, deterministic=deterministic, confidence=0.88)
    if provider == "mock_shadow_schema_error":
        return {"canonical_query": message, "extracted_slots": [], "confidence": "bad"}
    if provider == "openai":
        return await _call_openai_rewrite(model=model, message=message, deterministic=deterministic)
    raise RuntimeError(f"Unsupported LLM query rewrite provider: {provider}")


def _mock_rewrite_payload(
    message: str,
    *,
    deterministic: QueryRewriteResult,
    confidence: float,
) -> dict[str, Any]:
    compact = "".join(message.strip().split())
    slots = dict(deterministic.extracted_slots)
    if "低置信" in compact:
        confidence = 0.42
    if "鼓楼" in compact:
        slots.setdefault("city", "北京")
        slots.setdefault("area", "鼓楼")
    if "亮马桥" in compact:
        slots.setdefault("city", "北京")
        slots.setdefault("area", "亮马桥")
    if "奉贤行政服务中心" in compact:
        slots.setdefault("city", "上海")
        slots.setdefault("area", "奉贤行政服务中心")
    if "热干面" in compact:
        slots.setdefault("food_item", "热干面")
    if "川菜" in compact:
        slots.setdefault("cuisine", "川菜")
    if "火锅" in compact:
        slots.setdefault("cuisine", "火锅")
    if "烤肉" in compact:
        slots.setdefault("cuisine", "烤肉")
    if any(term in compact for term in ("帮我找", "有啥好吃", "有什么好吃", "选一个", "选一家")):
        slots.setdefault("task", "choose_restaurant")
    if slots.get("area") and not slots.get("venue"):
        slots["location_state"] = "in_area"
    return {
        "canonical_query": _canonical_query_from_slots(
            original=message,
            fallback=deterministic.canonical_query,
            slots=slots,
        ),
        "extracted_slots": slots,
        "confidence": confidence,
        "notes": ["mock LLM rewrite suggestion"],
    }


async def _call_openai_rewrite(
    *,
    model: str,
    message: str,
    deterministic: QueryRewriteResult,
) -> dict[str, Any]:
    settings = get_settings()
    api_key = getattr(settings, "openai_api_key", None)
    if api_key is None:
        raise RuntimeError("OpenAI API key is missing.")

    model_name = model if model and model != "none" else str(getattr(settings, "openai_model", "gpt-4.1-mini"))
    base_url = str(getattr(settings, "openai_base_url", "https://api.openai.com/v1")).rstrip("/")
    timeout = float(getattr(settings, "llm_timeout_seconds", 10.0) or 10.0)
    payload = {
        "model": model_name,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是皮皮 Agent 的 query rewrite 模块。只返回 JSON，不回答用户，不推荐店，"
                    "不选择工具。你只能提取和规范化用户原句里的槽位。不要覆盖确定信息。"
                    "JSON 形状必须是 {\"canonical_query\": str, \"extracted_slots\": object, "
                    "\"confidence\": number, \"notes\": [str]}。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "original_query": message,
                        "deterministic_rewrite": deterministic.model_dump(mode="json"),
                        "allowed_slots": [
                            "city",
                            "area",
                            "venue",
                            "food_item",
                            "cuisine",
                            "party_size",
                            "spice_preference",
                            "taste_preference",
                            "budget_preference",
                            "user_profile",
                            "task",
                            "location_state",
                        ],
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"OpenAI rewrite request failed with HTTP {response.status_code}: {_safe_text(response)}")
    data = response.json()
    content = _extract_openai_content(data)
    if content is None:
        raise RuntimeError("OpenAI rewrite response did not include message content.")
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise RuntimeError("OpenAI rewrite response content was not a JSON object.")
    return parsed


def _result(
    *,
    enabled: bool,
    provider: str,
    model: str,
    status: LlmRewriteStatus,
    original_query: str,
    started: float,
    canonical_query: str | None = None,
    extracted_slots: dict[str, Any] | None = None,
    rewrite_confidence: float | None = None,
    notes: list[str] | None = None,
    error: str | None = None,
) -> LlmQueryRewriteResult:
    return LlmQueryRewriteResult(
        enabled=enabled,
        provider=provider,
        model=model,
        status=status,
        original_query=original_query,
        canonical_query=canonical_query,
        extracted_slots=dict(extracted_slots or {}),
        rewrite_confidence=rewrite_confidence,
        notes=list(notes or []),
        error=error,
        latency_ms=round((time.perf_counter() - started) * 1000, 3),
    )


def _clean_slots(slots: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "city",
        "area",
        "venue",
        "food_item",
        "cuisine",
        "party_size",
        "spice_preference",
        "taste_preference",
        "budget_preference",
        "user_profile",
        "task",
        "location_state",
    }
    return {key: value for key, value in slots.items() if key in allowed and not _is_empty_slot(value)}


def _canonical_query_from_slots(*, original: str, fallback: str | None, slots: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("city", "area", "venue", "food_item", "cuisine", "task"):
        value = slots.get(key)
        if value:
            parts.append(str(value))
    if slots.get("spice_preference"):
        parts.append(str(slots["spice_preference"]))
    tastes = slots.get("taste_preference")
    if isinstance(tastes, list):
        parts.extend(str(item) for item in tastes if item)
    elif tastes:
        parts.append(str(tastes))
    if slots.get("party_size"):
        parts.append(f"{slots['party_size']}人")
    return " ".join(parts) if parts else str(fallback or original)


def _is_empty_slot(value: Any) -> bool:
    return value in (None, "", [], {})


def _format_validation_error(exc: ValidationError) -> str:
    return "; ".join(error.get("msg", "") for error in exc.errors()) or str(exc)


def _extract_openai_content(data: dict[str, Any]) -> str | None:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    return content if isinstance(content, str) else None


def _safe_text(response: httpx.Response) -> str:
    text = response.text
    return text[:400] if text else ""
