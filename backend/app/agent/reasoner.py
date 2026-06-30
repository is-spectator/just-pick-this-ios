from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError

from app.agent.model_adapter import (
    DeterministicPipiModelAdapter,
    get_deterministic_model_adapter,
)
from app.agent.schemas import AnswerDecision, ReasonerDecision, ToolDecision
from app.config import get_settings
from app.harness.evidence_evaluator import is_card_ready_hit
from app.harness.input_gate import InputGateResult, direct_answer_for_gate, run_input_gate


class DeterministicReasoner:
    """Rule-based PipiLoop reasoner that chooses tools but never writes cards itself."""

    def __init__(self, *, adapter: DeterministicPipiModelAdapter | None = None) -> None:
        self.adapter = adapter or get_deterministic_model_adapter()

    async def next(self, state: Any) -> ReasonerDecision:
        last_tool = _last_tool_record(state)
        if last_tool is not None and _record_tool_name(last_tool) != "search_knowledge":
            return _answer_after_tool(last_tool)

        gate = _gate_for_state(state)
        allowed_tools = _allowed_tools(state, gate)
        intent = _intent_for_state(state, gate)
        latest_user_context = _latest_user_context(state)

        if not gate.should_enter_loop:
            return AnswerDecision(
                message=direct_answer_for_gate(
                    gate,
                    _user_message(state),
                    latest_user_context=latest_user_context,
                )
            )

        active_help_card_id = _active_help_card_id(state)
        if intent == "publish_help" and "publish_help_card" in allowed_tools:
            return ToolDecision(
                tool_name="publish_help_card",
                tool_args={"help_card_id": active_help_card_id},
                reason="User approved publishing the active help card.",
            )

        if intent == "update_help_card" and "update_help_card" in allowed_tools:
            return ToolDecision(
                tool_name="update_help_card",
                tool_args={
                    "help_card_id": active_help_card_id,
                    "context_text": _user_message(state),
                },
                reason="User added constraints for the active help card.",
            )

        if intent == "one_liner_answer" and "submit_one_liner_answer" in allowed_tools:
            return ToolDecision(
                tool_name="submit_one_liner_answer",
                tool_args={
                    "help_card_id": active_help_card_id,
                    "raw_text": _user_message(state),
                },
                reason="One-liner is human evidence, not a final answer.",
            )

        if intent == "finalize_request" and "finalize_help_card" in allowed_tools:
            return ToolDecision(
                tool_name="finalize_help_card",
                tool_args={"help_card_id": active_help_card_id},
                reason="Finalize after accumulated human answers.",
            )

        should_search = bool(gate.should_retrieve or intent in {"decision_request", "help_request"})
        if (
            should_search
            and "search_knowledge" in allowed_tools
            and not _has_tool_result(state, "search_knowledge")
        ):
            return ToolDecision(
                tool_name="search_knowledge",
                tool_args={
                    "query": _user_message(state),
                    "question_id": _metadata(state).get("question_id"),
                    "user_id": _metadata(state).get("user_id"),
                    "limit": 8,
                },
                reason="Pipi retrieves knowledge before choosing a recommendation/help tool.",
            )

        strongest_evidence = _retrieval_hits(state)
        if (
            "create_recommendation_card" in allowed_tools
            and _has_card_ready_evidence(strongest_evidence)
        ):
            return ToolDecision(
                tool_name="create_recommendation_card",
                tool_args=_recommendation_args_from_hits(state, strongest_evidence),
                reason="Evidence is strong enough and includes trusted card media or place evidence.",
            )

        if "draft_help_card" in allowed_tools:
            return ToolDecision(
                tool_name="draft_help_card",
                tool_args=_draft_help_args(state),
                reason="No trusted evidence; draft a help card instead of forcing a card.",
            )

        return AnswerDecision(
            message=direct_answer_for_gate(
                gate,
                _user_message(state),
                latest_user_context=latest_user_context,
            )
        )


class OpenAIReasoner:
    """OpenAI-backed product reasoner kept inside the PipiLoop tool contract."""

    def __init__(self, *, fallback: DeterministicReasoner | None = None) -> None:
        self.fallback = fallback or DeterministicReasoner()

    async def next(self, state: Any) -> ReasonerDecision:
        baseline = await self.fallback.next(state)
        settings = get_settings()
        if settings.openai_api_key is None:
            return _annotate_decision(
                baseline,
                llm_provider="openai",
                llm_status="disabled",
                llm_fallback=True,
                llm_error_type="disabled",
                llm_error="OPENAI_API_KEY is missing.",
            )

        try:
            raw_decision = await _call_openai_reasoner(
                state=state,
                baseline=baseline,
            )
            llm_decision = _REASONER_DECISION_ADAPTER.validate_python(_coerce_decision_object(raw_decision))
            guarded = _guard_openai_decision(
                state=state,
                baseline=baseline,
                llm_decision=llm_decision,
            )
            return _annotate_decision(
                guarded,
                llm_provider="openai",
                llm_status="success",
                llm_raw_decision=_dump_decision(llm_decision),
            )
        except Exception as exc:
            return _annotate_decision(
                baseline,
                llm_provider="openai",
                llm_status="fallback",
                llm_fallback=True,
                llm_error_type=_llm_error_type(exc),
                llm_error=str(exc)[:500],
            )


def get_product_reasoner() -> DeterministicReasoner | OpenAIReasoner:
    settings = get_settings()
    if settings.pipi_model_provider == "openai":
        return OpenAIReasoner()
    return DeterministicReasoner()


_REASONER_DECISION_ADAPTER = TypeAdapter(ReasonerDecision)


async def _call_openai_reasoner(*, state: Any, baseline: ReasonerDecision) -> dict[str, Any] | str:
    settings = get_settings()
    api_key = settings.openai_api_key
    if api_key is None:
        raise RuntimeError("OPENAI_API_KEY is missing.")

    model_name = settings.openai_model
    base_url = settings.openai_base_url.rstrip("/")
    payload = {
        "model": model_name,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": _openai_reasoner_messages(state=state, baseline=baseline),
    }
    async with httpx.AsyncClient(timeout=float(settings.openai_timeout_seconds)) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

    if response.status_code >= 400:
        raise RuntimeError(f"OpenAI reasoner request failed with HTTP {response.status_code}: {response.text[:500]}")
    content = _extract_openai_content(response.json())
    if content is None:
        raise RuntimeError("OpenAI reasoner response did not include message content.")
    return content


def _openai_reasoner_messages(*, state: Any, baseline: ReasonerDecision) -> list[dict[str, str]]:
    gate = _gate_for_state(state)
    task_payload = {
        "user_message": _user_message(state),
        "intent": _intent_for_state(state, gate),
        "allowed_tools": _allowed_tools(state, gate),
        "context_pack": _redact_and_shrink(_context_pack(state)),
        "tool_results": _redact_and_shrink(_tool_results(state)),
        "baseline_contract_decision": _dump_decision(baseline),
    }
    return [
        {
            "role": "system",
            "content": (
                "你是皮皮 Agent 的 product reasoner，必须在 Harness 约束内工作。"
                "你每轮只能输出一个 JSON object，且只能是二选一：\n"
                '1. {"type":"tool","tool_name":"<allowed tool>","tool_args":{},"reason":"..."}\n'
                '2. {"type":"answer","message":"...","ui_events":[],"data":{}}\n'
                "硬规则：\n"
                "- 不能绕过 tool/function call，不能直接吐推荐卡 JSON 或求助卡 JSON。\n"
                "- tool_name 必须来自 allowed_tools，不允许自造工具。\n"
                "- greeting/smalltalk/app_help 不能调用工具，只能 answer。\n"
                "- decision_request/help_request 首轮必须先 search_knowledge；不能跳过检索直接出卡。\n"
                "- search_knowledge 后如果证据不足、无 evidence_ids、无 approved answer，必须 draft_help_card。\n"
                "- create_recommendation_card/draft_help_card 等 card tool_result 返回后，下一轮必须 answer 收口。\n"
                "- 已有 card/help_card 工具结果时，answer 只能引用 tool_result 的 ui_events 和 data，不能编造新卡。\n"
                "如果 baseline_contract_decision 要先 search_knowledge，不要跳过检索；如果已有工具结果并该收口，输出 answer。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(task_payload, ensure_ascii=False, separators=(",", ":")),
        },
    ]


def _guard_openai_decision(
    *,
    state: Any,
    baseline: ReasonerDecision,
    llm_decision: ReasonerDecision,
) -> ReasonerDecision:
    if isinstance(baseline, AnswerDecision):
        if not isinstance(llm_decision, AnswerDecision):
            return baseline
        if baseline.ui_events:
            return AnswerDecision(
                message=llm_decision.message or baseline.message,
                ui_events=baseline.ui_events,
                data=baseline.data,
            )
        return llm_decision

    if not isinstance(llm_decision, ToolDecision):
        return baseline

    allowed_tools = set(_allowed_tools(state, _gate_for_state(state)))
    if llm_decision.tool_name not in allowed_tools:
        return baseline

    if _must_keep_baseline_tool(state, baseline, llm_decision):
        return baseline

    return ToolDecision(
        tool_name=llm_decision.tool_name,
        tool_args=baseline.tool_args if llm_decision.tool_name == baseline.tool_name else llm_decision.tool_args,
        reason=llm_decision.reason or baseline.reason,
    )


def _must_keep_baseline_tool(
    state: Any,
    baseline: ToolDecision,
    llm_decision: ToolDecision,
) -> bool:
    if baseline.tool_name == llm_decision.tool_name:
        return False
    if baseline.tool_name == "search_knowledge" and not _has_tool_result(state, "search_knowledge"):
        return True
    if baseline.tool_name in {
        "create_recommendation_card",
        "draft_help_card",
        "publish_help_card",
        "update_help_card",
        "submit_one_liner_answer",
        "finalize_help_card",
    }:
        return True
    return False


def _coerce_decision_object(raw_decision: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(raw_decision, str):
        raw_decision = json.loads(raw_decision)
    if not isinstance(raw_decision, dict):
        raise TypeError("OpenAI reasoner returned a non-object decision.")
    return raw_decision


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
    return None


def _annotate_decision(decision: ReasonerDecision, **fields: Any) -> ReasonerDecision:
    return decision.model_copy(update=fields)


def _llm_error_type(exc: Exception) -> str:
    if isinstance(exc, (json.JSONDecodeError, TypeError, ValidationError)):
        return "schema_error"
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return "timeout"
    return "provider_error"


def _dump_decision(decision: Any) -> dict[str, Any]:
    if hasattr(decision, "model_dump"):
        return decision.model_dump(mode="json")
    if isinstance(decision, dict):
        return dict(decision)
    return {}


def _redact_and_shrink(value: Any, *, max_chars: int = 10000) -> Any:
    redacted = _redact_secretish_values(value)
    encoded = json.dumps(redacted, ensure_ascii=False, default=str)
    if len(encoded) <= max_chars:
        return redacted
    return {"truncated": True, "preview": encoded[:max_chars]}


def _redact_secretish_values(value: Any) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(marker in key_text for marker in ("api_key", "token", "authorization", "password", "secret")):
                output[str(key)] = "[REDACTED]"
            else:
                output[str(key)] = _redact_secretish_values(item)
        return output
    if isinstance(value, list):
        return [_redact_secretish_values(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_secretish_values(item) for item in value]
    return value


def _gate_for_state(state: Any) -> InputGateResult:
    metadata = _metadata(state)
    raw = metadata.get("input_gate_result") or metadata.get("input_gate")
    if isinstance(raw, InputGateResult):
        return raw
    if isinstance(raw, dict):
        try:
            return InputGateResult.model_validate(raw)
        except Exception:
            pass

    active_help_card_id = _active_help_card_id(state)
    latest_user_context = _latest_user_context(state)
    return run_input_gate(
        _user_message(state),
        active_help_card_id=active_help_card_id,
        in_answer_context=bool(active_help_card_id),
        latest_user_context=latest_user_context,
        client_context=dict(metadata.get("client_context") or {}),
    )


def _allowed_tools(state: Any, gate: InputGateResult) -> list[str]:
    state_allowed = list(_value(state, "allowed_tools") or [])
    return list(dict.fromkeys([*gate.allowed_tools, *state_allowed]))


def _intent_for_state(state: Any, gate: InputGateResult) -> str:
    return str(
        _value(state, "intent")
        or _value(state, "intent_type")
        or _metadata(state).get("intent_type")
        or gate.intent_type
    )


def _answer_after_tool(record: dict[str, Any]) -> AnswerDecision:
    tool_name = _record_tool_name(record)
    result = _record_tool_result(record)
    data = _tool_data(result)
    if not bool(result.get("ok", True)):
        return AnswerDecision(
            message="我还缺一点能直接拍板的依据。你补一句位置、口味或预算，我继续帮你收成一个。",
            data={},
        )
    return AnswerDecision(
        message=_message_after_tool(tool_name, data),
        ui_events=list(data.get("ui_events") or []),
        data={_data_key_after_tool(tool_name): data} if data else {"tool_result": data},
    )


def _last_tool_record(state: Any) -> dict[str, Any] | None:
    results = _tool_results(state)
    if not results:
        return None
    last = results[-1]
    return dict(last) if isinstance(last, dict) else None


def _has_tool_result(state: Any, tool_name: str) -> bool:
    return any(
        isinstance(record, dict) and _record_tool_name(record) == tool_name
        for record in _tool_results(state)
    )


def _tool_results(state: Any) -> list[Any]:
    return list(_value(state, "tool_results") or [])


def _record_tool_name(record: dict[str, Any]) -> str:
    decision = record.get("decision") if isinstance(record.get("decision"), dict) else {}
    result = _record_tool_result(record)
    return str(decision.get("tool_name") or result.get("tool_name") or "")


def _record_tool_result(record: dict[str, Any]) -> dict[str, Any]:
    result = record.get("tool_result")
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    if isinstance(result, dict):
        return result
    return {}


def _retrieval_hits(state: Any) -> list[dict[str, Any]]:
    context_pack = _context_pack(state)
    for candidates in (
        context_pack.get("strongest_evidence"),
        context_pack.get("retrieval_hits"),
        (context_pack.get("retrieval_run") or {}).get("hits"),
    ):
        if isinstance(candidates, list) and candidates:
            return [_normalize_hit(item) for item in candidates if isinstance(item, dict)]

    for record in reversed(_tool_results(state)):
        result = _record_tool_result(dict(record))
        if result.get("tool_name") != "search_knowledge":
            continue
        data = _tool_data(result)
        hits = data.get("retrieval_hits") or data.get("hits") or (data.get("retrieval_run") or {}).get("hits")
        if isinstance(hits, list):
            return [_normalize_hit(item) for item in hits if isinstance(item, dict)]
    return []


def _tool_data(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data")
    if isinstance(data, dict):
        return data
    output = result.get("output")
    if isinstance(output, dict):
        return output
    return {}


def _normalize_hit(hit: dict[str, Any]) -> dict[str, Any]:
    if "payload" in hit:
        return dict(hit)
    metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
    payload = metadata.get("payload") if isinstance(metadata.get("payload"), dict) else metadata
    return {
        **hit,
        "source_id": hit.get("evidence_id") or hit.get("source_id") or hit.get("id"),
        "score": hit.get("score"),
        "payload": payload,
    }


def _recommendation_args_from_hits(state: Any, hits: list[dict[str, Any]]) -> dict[str, Any]:
    primary = _first_card_ready_hit(hits) or (hits[0] if hits else {})
    payload = dict(primary.get("payload") or {})
    metadata = _metadata(state)
    title = (
        payload.get("card_title")
        or payload.get("item_title")
        or payload.get("title")
        or primary.get("title")
        or "就选这个"
    )
    decision_text = (
        payload.get("decision_factor")
        or payload.get("reason")
        or payload.get("text")
        or primary.get("text")
        or primary.get("title")
        or "这一个证据最稳。"
    )
    evidence_ids = [
        str(hit.get("source_id") or hit.get("id"))
        for hit in hits
        if hit.get("source_id") or hit.get("id")
    ]
    return {
        "question_id": metadata.get("question_id") or _value(state, "turn_id"),
        "user_id": metadata.get("user_id"),
        "intent_answer_id": payload.get("intent_answer_id"),
        "item": {
            "title": str(title),
            "subtitle": payload.get("subtitle"),
            "category": payload.get("target_type") or payload.get("category"),
        },
        "decision_factor": {
            "text": str(decision_text),
            "key": payload.get("decision_factor_key"),
        },
        "image_asset_id": payload.get("image_asset_id"),
        "image_required": False,
        "evidence_ids": evidence_ids,
        "retrieval_run_id": metadata.get("retrieval_run_id") or _retrieval_run_id(state),
        "confidence": max(0.7, min(float(primary.get("score") or 0.78), 1.0)),
    }


def _draft_help_args(state: Any) -> dict[str, Any]:
    metadata = _metadata(state)
    message = _user_message(state)
    compressed = _compress_help_card_problem(message)
    return {
        "question_id": metadata.get("question_id") or _value(state, "turn_id"),
        "owner_user_id": metadata.get("user_id") or "unknown-user",
        "title": compressed["title"],
        "context": compressed["context"],
        "wants": compressed["wants"],
        "avoids": compressed["avoids"],
        "constraints": compressed["constraints"],
    }


def _first_card_ready_hit(hits: list[dict[str, Any]]) -> dict[str, Any] | None:
    for hit in hits:
        if is_card_ready_hit(hit):
            return hit
    return None


def _retrieval_run_id(state: Any) -> str | None:
    context_pack = _context_pack(state)
    retrieval_run = context_pack.get("retrieval_run")
    if isinstance(retrieval_run, dict) and retrieval_run.get("id"):
        return str(retrieval_run["id"])
    for record in reversed(_tool_results(state)):
        result = _record_tool_result(dict(record))
        if result.get("tool_name") != "search_knowledge":
            continue
        data = _tool_data(result)
        if data.get("retrieval_run_id"):
            return str(data["retrieval_run_id"])
    return None


def _specific_wants(message: str) -> list[str]:
    wants: list[str] = []
    if "清淡" in message or "清爽" in message:
        wants.append("清淡口味")
    if "小众" in message:
        wants.append("小众")
    if "逛街" in message:
        wants.append("逛街顺路")
    if "美妆" in message:
        wants.append("美妆")
    if "川菜" in message:
        wants.append("川菜")
    if "贵州菜" in message:
        wants.append("贵州菜")
    if "韩餐" in message or "韩国菜" in message:
        wants.append("韩餐")
    if "热干面" in message:
        wants.append("热干面")
    if "点菜" in message or "帮我点" in message or "怎么点" in message:
        wants.append("到店点菜")
    if "海底捞" in message:
        wants.append("海底捞点单")
    if not wants:
        wants.append(_fallback_want(message))
    return wants


def _specific_avoids(message: str) -> list[str]:
    avoids: list[str] = []
    if "不去明洞" in message or "别去明洞" in message:
        avoids.append("明洞")
    if "游客区" in message:
        avoids.append("游客区")
    if _contains_non_spicy_preference(message):
        avoids.append("太辣")
    if "排队" in message and ("不" in message or "少" in message):
        avoids.append("久排队")
    return avoids


def _compress_help_card_problem(message: str) -> dict[str, Any]:
    context = _help_card_context(message)
    wants = _specific_wants(message)
    avoids = _specific_avoids(message)
    constraints = _help_card_constraints(message)
    title = _help_card_title(message, context=context, wants=wants)
    if title in {"北京这顿饭，求一个", "这顿饭，求一个"}:
        title = _fallback_help_title(context=context, wants=wants)
    return {
        "title": title,
        "context": context,
        "wants": wants,
        "avoids": avoids,
        "constraints": constraints,
    }


def _help_card_context(message: str) -> dict[str, Any]:
    context: dict[str, Any] = {"original_query": message}
    city = _extract_city(message)
    if city:
        context["city"] = city
    area = _extract_area(message)
    if area:
        context["area"] = area
    venue = _extract_venue(message)
    if venue:
        context["venue"] = venue
    cuisine = _extract_cuisine_or_food(message)
    if cuisine:
        context["food_or_cuisine"] = cuisine
    if "逛街" in message:
        context["scene"] = "逛街"
    if "约会" in message:
        context["scene"] = "约会"
    party_size = _extract_party_size(message)
    if party_size is not None:
        context["party_size"] = party_size
    if _contains_non_spicy_preference(message):
        context["spicy_preference"] = "not_spicy"
    if "广东人" in message:
        context["user_profile"] = "guangdong"
        context["taste_preference"] = "light"
    return context


def _help_card_constraints(message: str) -> dict[str, Any]:
    constraints: dict[str, Any] = {}
    party_size = _extract_party_size(message)
    if party_size is not None:
        constraints["party_size"] = party_size
    if _contains_non_spicy_preference(message):
        constraints["spicy_preference"] = "not_spicy"
    if "预算不高" in message or "便宜" in message:
        constraints["budget_preference"] = "budget_friendly"
    missing_info: list[str] = []
    if not _extract_area(message) and not _extract_venue(message):
        missing_info.append("location_or_venue")
    if not _extract_cuisine_or_food(message) and not ("逛街" in message or "美妆" in message):
        missing_info.append("target_preference")
    constraints["missing_info"] = missing_info
    return constraints


def _help_card_title(message: str, *, context: dict[str, Any], wants: list[str]) -> str:
    venue = str(context.get("venue") or "")
    area = str(context.get("area") or context.get("city") or "")
    food = str(context.get("food_or_cuisine") or "")
    scene = str(context.get("scene") or "")
    if venue and ("点菜" in message or "帮我点" in message or "怎么点" in message):
        return f"{venue}怎么点，求一个"
    if area and food:
        return f"{area}{food}，求一个"
    if area and scene:
        suffix = "小众" if "小众" in wants else scene
        return f"{area}{suffix}{scene if suffix != scene else ''}，求一个"
    if area and wants:
        return f"{area}{wants[0]}，求一个"
    if venue:
        return f"{venue}这题，求一个"
    return _fallback_help_title(context=context, wants=wants)


def _fallback_help_title(*, context: dict[str, Any], wants: list[str]) -> str:
    area = str(context.get("area") or context.get("city") or "").strip()
    want = wants[0] if wants else "具体选择"
    if area:
        return f"{area}{want}，求一个"
    return f"{want}，求一个"


def _fallback_want(message: str) -> str:
    food = _extract_cuisine_or_food(message)
    if food:
        return food
    if "逛街" in message:
        return "逛街选择"
    return "具体选择"


def _extract_city(message: str) -> str | None:
    for city in ("北京", "上海", "广州", "深圳", "首尔", "韩国"):
        if city in message:
            return city
    return None


def _extract_area(message: str) -> str | None:
    areas = ("望京 SOHO", "望京SOHO", "朝阳区", "三里屯", "南锣鼓巷", "五道口", "韩国", "明洞")
    for area in areas:
        if area == "明洞" and ("不去明洞" in message or "别去明洞" in message):
            continue
        if area in message:
            return "望京 SOHO" if area == "望京SOHO" else area
    return None


def _extract_venue(message: str) -> str | None:
    for venue in ("海底捞", "四季民福", "喜晋道"):
        if venue in message:
            return venue
    if "没听过的小店" in message or "小店" in message:
        return "未知小店"
    return None


def _extract_cuisine_or_food(message: str) -> str | None:
    for food in ("热干面", "贵州菜", "川菜", "韩餐", "韩国菜", "火锅", "烤鸭", "粤菜", "湘菜"):
        if food in message:
            return "韩餐" if food == "韩国菜" else food
    return None


def _extract_party_size(message: str) -> int | None:
    if "两个人" in message or "2个人" in message or "俩人" in message:
        return 2
    if "一个人" in message or "1个人" in message:
        return 1
    return None


def _contains_non_spicy_preference(message: str) -> bool:
    return any(term in message for term in ("不辣", "不能吃辣", "不太能吃辣", "不要辣", "少辣"))


def _has_card_ready_evidence(hits: list[dict[str, Any]]) -> bool:
    for hit in hits:
        if is_card_ready_hit(hit):
            return True
    return False


def _has_verified_non_ai_image(payload: dict[str, Any]) -> bool:
    if payload.get("has_verified_non_ai_image") and payload.get("image_asset_id"):
        return True
    image_asset = payload.get("image_asset")
    if not isinstance(image_asset, dict):
        return False
    verified = bool(image_asset.get("verified") or image_asset.get("is_verified"))
    is_ai_generated = bool(image_asset.get("is_ai_generated"))
    return verified and not is_ai_generated and bool(
        image_asset.get("id") or payload.get("image_asset_id")
    )


def _message_after_tool(tool_name: str, data: dict[str, Any]) -> str:
    if tool_name == "create_recommendation_card":
        return "别查了，就这个。"
    if tool_name == "draft_help_card":
        return "这题我不硬选，先帮你求一个。"
    if tool_name == "publish_help_card":
        return "发出去了，等懂的人来一句。"
    if tool_name == "submit_one_liner_answer":
        if data.get("finalization_ready"):
            return "收到，这句我记上了，答案也够收口了。"
        return "收到，这句我记上了。"
    if tool_name == "finalize_help_card":
        if data.get("status") == "needs_more_answers":
            return "还差几句真人反馈，我先不硬收口。"
        return "我收好了，就选这个。"
    if tool_name == "update_help_card":
        return "我把这句补进当前求一个里了。"
    return "好了。"


def _data_key_after_tool(tool_name: str) -> str:
    if tool_name == "create_recommendation_card":
        return "recommendation_card"
    if tool_name in {"draft_help_card", "update_help_card", "publish_help_card"}:
        return "help_card"
    if tool_name == "submit_one_liner_answer":
        return "help_answer"
    if tool_name == "finalize_help_card":
        return "finalize"
    return "tool_result"


def _active_help_card_id(state: Any) -> str | None:
    context_pack = _context_pack(state)
    active = context_pack.get("active_help_card")
    if isinstance(active, dict):
        value = active.get("id") or active.get("help_card_id")
        if value:
            return str(value)
    outputs = context_pack.get("tool_outputs")
    if isinstance(outputs, dict):
        for tool_name in ("draft_help_card", "update_help_card", "publish_help_card"):
            output = outputs.get(tool_name)
            if isinstance(output, dict) and output.get("help_card_id"):
                return str(output["help_card_id"])
    metadata = _metadata(state)
    value = metadata.get("active_help_card_id") or metadata.get("help_card_id")
    return str(value) if value else None


def _latest_user_context(state: Any) -> str | None:
    metadata = _metadata(state)
    value = metadata.get("latest_user_context")
    return str(value) if value else None


def _user_message(state: Any) -> str:
    return str(_value(state, "user_message") or "")


def _metadata(state: Any) -> dict[str, Any]:
    value = _value(state, "metadata")
    return dict(value) if isinstance(value, dict) else {}


def _context_pack(state: Any) -> dict[str, Any]:
    value = _value(state, "context_pack")
    return dict(value) if isinstance(value, dict) else {}


def _value(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


__all__ = ["DeterministicReasoner", "OpenAIReasoner", "get_product_reasoner"]
