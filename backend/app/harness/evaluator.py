"""Deterministic evaluator checks for Pipi harness artifacts."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.harness.evidence_evaluator import is_generic_decision_factor


SuggestedNextAction = Literal["continue", "retry_tool", "draft_help_card", "answer_safe"]


class EvaluationResult(BaseModel):
    """Shared Pydantic result for evaluator and answer-gate checks."""

    model_config = ConfigDict(extra="allow")

    passed: bool
    quality_score: float = Field(default=1.0, ge=0.0, le=1.0)
    score: float = Field(default=1.0, ge=0.0, le=1.0)
    issues: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    reason: str = ""
    suggested_next_action: SuggestedNextAction = "continue"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def sync_legacy_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if "score" not in normalized and "quality_score" in normalized:
            normalized["score"] = normalized["quality_score"]
        if "quality_score" not in normalized and "score" in normalized:
            normalized["quality_score"] = normalized["score"]
        if "errors" not in normalized and "issues" in normalized:
            normalized["errors"] = list(normalized.get("issues") or [])
        if "issues" not in normalized and "errors" in normalized:
            normalized["issues"] = list(normalized.get("errors") or [])
        if "reason" not in normalized:
            issue_text = "; ".join(str(item) for item in normalized.get("issues") or [])
            normalized["reason"] = issue_text or "passed"
        return normalized

    @property
    def ok(self) -> bool:
        return self.passed

    @property
    def failed(self) -> bool:
        return not self.passed


GENERIC_HELP_TITLES = {
    "北京这顿饭，求一个",
    "这顿饭，求一个",
    "求一个",
    "求推荐",
    "求助",
    "推荐一个",
    "给我推荐一个",
    "帮我选一个",
    "帮我推荐一个",
    "帮我问问",
    "问问大家",
    "不知道选什么",
    "不知道吃什么",
    "求一个靠谱推荐",
    "求一个靠谱选择",
    "求一个具体推荐",
    "一个具体推荐",
    "想找一个",
}
GENERIC_WANTS = {
    "好吃",
    "好用",
    "方便",
    "靠谱",
    "稳",
    "稳妥",
    "省心",
    "不踩雷",
    "少踩雷",
    "别踩雷",
    "直接告诉我",
    "别让我查",
    "不用查",
    "一个推荐",
    "具体推荐",
    "一个具体推荐",
    "一个具体可执行的选择",
    "一个具体可执行选择",
    "一个能直接照着选的建议",
}
GENERIC_AVOIDS = {
    "踩雷",
    "不要踩雷",
    "别踩雷",
    "多个选项",
    "太多选项",
    "一堆选项",
    "选择困难",
    "不靠谱",
    "不稳定证据",
    "硬推榜单",
    "别让我查",
}
GENERIC_CONTEXTS = {
    "北京",
    "附近",
    "这附近",
    "这顿饭",
    "这题",
    "证据不足",
    "证据不够",
    "先求一个",
    "求懂的人来一句",
    "不知道怎么选",
}
FORBIDDEN_CARD_FIELDS = {"reasons", "bullets", "followups", "why_questions", "not_for", "warning"}
HAIDILAO_ALIASES = ("海底捞", "海底捞火锅", "haidilao")
VENUE_ORDERING_HINTS = (
    "帮我点",
    "怎么点",
    "点菜",
    "点什么",
    "来什么",
    "吃什么",
    "不吃辣",
    "不太能吃辣",
    "番茄锅",
    "菌汤锅",
    "你决定",
)
VENUE_PRESENCE_HINTS = ("我在", "现在在", "到", "到了", "已经到", "店里")
NOT_IN_VENUE_HINTS = ("附近", "不在店里", "不想吃火锅", "咖啡")
AREA_RESTAURANT_LEAK_TERMS = ("川菜馆候选", "三里屯川菜", "附近餐厅")

_GENERIC_TITLE_PARTS = (
    "帮我",
    "给我",
    "大家",
    "问问",
    "有没有",
    "不知道",
    "怎么选",
    "吃什么",
    "选什么",
    "求",
    "一个",
    "靠谱",
    "具体",
    "推荐",
    "选择",
    "建议",
    "答案",
    "帮忙",
    "一下",
    "直接",
    "想找",
    "想要",
)
_CONTEXT_DETAIL_KEYS = {
    "cuisine",
    "diet",
    "occasion",
    "party_size",
    "people",
    "preference",
    "preferences",
    "scenario",
    "taste",
    "venue",
    "wants",
    "avoids",
    "constraints",
}
_CONTEXT_LOCATION_ONLY_KEYS = {
    "area",
    "city",
    "country",
    "district",
    "location",
    "location_hint",
    "place",
    "region",
}
_SPECIFIC_CONTEXT_MARKERS = (
    "不吃辣",
    "不太能吃辣",
    "两个人",
    "第一次",
    "点菜",
    "清淡",
    "川菜",
    "火锅",
    "美妆",
    "小众",
    "约会",
    "带爸妈",
    "预算",
    "不去",
    "不想",
    "想吃",
    "想买",
    "现场",
    "店里",
)


def evaluate_recommendation_card(card: Any) -> EvaluationResult:
    """Validate the one-card V0 recommendation contract."""

    errors: list[str] = []
    warnings: list[str] = []
    metadata: dict[str, Any] = {}

    data = _as_mapping(card)
    if data is None:
        return _result(errors=["recommendation_card_must_be_an_object"], warnings=warnings)

    if "decision_factors" in data:
        errors.append("recommendation_card_must_use_singular_decision_factor")

    decision_factor = data.get("decision_factor")
    decision_text = _decision_factor_text(decision_factor)
    if decision_factor is None:
        errors.append("recommendation_card_missing_decision_factor")
    elif isinstance(decision_factor, Sequence) and not isinstance(decision_factor, str):
        errors.append("recommendation_card_decision_factor_must_be_single")
    elif not decision_text:
        errors.append("recommendation_card_decision_factor_missing_text")
    elif is_generic_decision_factor(decision_text):
        errors.append("decision_factor_too_weak")
    elif isinstance(decision_factor, str):
        warnings.append("recommendation_card_decision_factor_should_be_object")

    item_titles: list[str] = []
    item = data.get("item")
    if item is not None:
        item_titles.extend(_titles_from_item(item))

    items = data.get("items")
    if items is not None:
        if isinstance(items, Sequence) and not isinstance(items, str):
            if len(items) != 1:
                errors.append("recommendation_card_must_have_exactly_one_item")
            elif items:
                item_titles.extend(_titles_from_item(items[0]))
        else:
            errors.append("recommendation_card_items_must_be_a_single_item_list")

    title = _clean_text(data.get("title"))
    unique_item_titles = {_normalize_for_compare(value) for value in item_titles if value}
    if not unique_item_titles:
        errors.append("recommendation_card_missing_item_title")
    elif len(unique_item_titles) > 1:
        errors.append("recommendation_card_has_ambiguous_titles")
    else:
        item_title = next((value for value in item_titles if value), "")
        metadata["title"] = item_title
        if title and _normalize_for_compare(title) != _normalize_for_compare(item_title):
            errors.append("recommendation_card_title_must_match_item_title")

    for field in FORBIDDEN_CARD_FIELDS:
        if field in data:
            errors.append(f"recommendation_card_forbidden_{field}")

    confidence = data.get("confidence")
    if confidence is not None:
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            errors.append("recommendation_card_confidence_must_be_number")
        else:
            metadata["confidence"] = confidence_value
            if confidence_value < 0.7:
                errors.append("recommendation_card_confidence_too_low")

    evidence_ids = _string_list(data.get("evidence_ids"))
    if evidence_ids:
        metadata["has_evidence_reference"] = True
        metadata["evidence_ids"] = evidence_ids
    else:
        errors.append("recommendation_card_missing_evidence_ids")
        if _has_evidence_reference(data):
            warnings.append("recommendation_card_evidence_ids_should_be_top_level")

    image_errors, image_warnings, image_metadata = _image_asset_quality(data)
    errors.extend(image_errors)
    warnings.extend(image_warnings)
    metadata.update(image_metadata)

    if decision_text:
        metadata["decision_factor_text"] = decision_text
    return _result(errors=errors, warnings=warnings, metadata=metadata)


def evaluate_help_card(help_card: Any) -> EvaluationResult:
    """Validate that a help card is not generic in title, wants, or avoids."""

    errors: list[str] = []
    warnings: list[str] = []
    metadata: dict[str, Any] = {}

    data = _as_mapping(help_card)
    if data is None:
        return _result(errors=["help_card_must_be_an_object"], warnings=warnings)

    title = _clean_text(data.get("title"))
    if not title:
        errors.append("help_card_missing_title")
    elif _is_generic_title(title):
        errors.append("help_card_title_too_generic")
    else:
        metadata["title"] = title

    context_value = data.get("context", data.get("context_text"))
    if not _has_nonempty_context(context_value):
        errors.append("help_card_missing_context")
    elif _is_generic_context(context_value):
        errors.append("help_card_context_too_generic")
    else:
        metadata["has_context"] = True

    wants = _string_list(data.get("wants"))
    avoids = _string_list(data.get("avoids"))

    if not wants:
        errors.append("help_card_missing_wants")
    else:
        generic_wants = [value for value in wants if _is_generic_want(value)]
        if len(generic_wants) == len(wants):
            errors.append("help_card_wants_too_generic")
        elif generic_wants:
            warnings.append("help_card_contains_generic_wants")
        metadata["wants"] = wants

    if not avoids:
        errors.append("help_card_missing_avoids")
    else:
        generic_avoids = [value for value in avoids if _is_generic_avoid(value)]
        if len(generic_avoids) == len(avoids):
            errors.append("help_card_avoids_too_generic")
        elif generic_avoids:
            warnings.append("help_card_contains_generic_avoids")
        metadata["avoids"] = avoids

    return _result(errors=errors, warnings=warnings, metadata=metadata)


def evaluate_venue_order_route(message: str, response: Any) -> EvaluationResult:
    """Check that a Haidilao ordering request routes as an in-venue ordering bundle."""

    errors: list[str] = []
    warnings: list[str] = []
    metadata: dict[str, Any] = {"route": "venue_order", "venue": "haidilao"}

    message_text = _clean_text(message)
    metadata["applicable"] = _is_haidilao_venue_order_request(message_text)
    if not metadata["applicable"]:
        metadata["reason"] = "message_not_haidilao_venue_order"
        return _result(errors=errors, warnings=warnings, metadata=metadata)

    response_data = _as_mapping(response)
    if response_data is None:
        return _result(
            errors=["venue_order_response_must_be_an_object"],
            warnings=warnings,
            metadata=metadata,
        )

    card = _extract_recommendation_card(response_data)
    location_state = _clean_text(
        response_data.get("location_state") or (card or {}).get("location_state")
    )
    target_type = _clean_text((card or {}).get("target_type"))
    title = _clean_text((card or {}).get("title"))
    subtitle = _clean_text((card or {}).get("subtitle"))
    decision_text = _decision_factor_text((card or {}).get("decision_factor")) if card else ""

    metadata.update(
        {
            "location_state": location_state,
            "target_type": target_type,
            "title": title,
            "subtitle": subtitle,
        }
    )

    if card is None:
        errors.append("venue_order_missing_recommendation_card")
    if location_state and location_state != "in_venue":
        errors.append("venue_order_should_route_in_venue")
    elif not location_state:
        errors.append("venue_order_missing_location_state")
    if target_type and target_type != "ordering_bundle":
        errors.append("venue_order_should_return_ordering_bundle")
    elif card is not None and not target_type:
        errors.append("venue_order_missing_target_type")
    if any(term in title for term in AREA_RESTAURANT_LEAK_TERMS):
        errors.append("haidilao_route_overridden_by_area_restaurant")
    if card is not None and not decision_text:
        errors.append("venue_order_missing_decision_factor")

    ui_events = response_data.get("ui_events")
    if isinstance(ui_events, Sequence) and not isinstance(ui_events, str):
        if not any(
            isinstance(event, Mapping)
            and event.get("type") == "show_recommendation_card"
            and event.get("card_id")
            for event in ui_events
        ):
            errors.append("venue_order_missing_card_ui_event")

    combined_text = f"{title} {subtitle} {decision_text}".casefold()
    if card is not None and not any(alias.casefold() in combined_text for alias in HAIDILAO_ALIASES):
        warnings.append("venue_order_card_does_not_name_haidilao")

    return _result(errors=errors, warnings=warnings, metadata=metadata)


class Evaluator:
    """OO wrapper kept for harness callers that prefer an instance."""

    def evaluate_recommendation_card(self, card: Any) -> EvaluationResult:
        return evaluate_recommendation_card(card)

    def evaluate_help_card(self, help_card: Any) -> EvaluationResult:
        return evaluate_help_card(help_card)

    def evaluate_venue_order_route(self, message: str, response: Any) -> EvaluationResult:
        return evaluate_venue_order_route(message, response)

    def evaluate_response(self, message: str, response: Any) -> EvaluationResult:
        results: list[EvaluationResult] = []
        response_data = _as_mapping(response)
        if response_data is not None:
            card = _extract_recommendation_card(response_data)
            if card is not None:
                results.append(evaluate_recommendation_card(card))
            help_card = _extract_help_card(response_data)
            if help_card is not None:
                results.append(evaluate_help_card(help_card))

        route_result = evaluate_venue_order_route(message, response)
        if route_result.metadata.get("applicable"):
            results.append(route_result)
        if results:
            return _merge_results(*results)
        return route_result

    def evaluate_tool_result(self, *, state: Any, decision: Any, tool_result: Any) -> EvaluationResult:
        tool_data = _as_mapping(tool_result) or {}
        data = _mapping_payload(tool_data, tool_result)
        if not bool(tool_data.get("ok", getattr(tool_result, "ok", True))):
            return EvaluationResult(
                passed=False,
                quality_score=0.0,
                score=0.0,
                issues=[
                    _clean_text(
                        tool_data.get("error_message")
                        or tool_data.get("error")
                        or getattr(tool_result, "error_message", None)
                    )
                    or "tool_failed"
                ],
                suggested_next_action="answer_safe",
            )
        if "recommendation_card" in data:
            card_result = evaluate_recommendation_card(data["recommendation_card"])
            route_result = evaluate_venue_order_route(
                str(getattr(state, "user_message", "") or ""),
                {"data": data, "recommendation_card": data["recommendation_card"]},
            )
            if route_result.metadata.get("applicable"):
                return _merge_results(card_result, route_result)
            return card_result
        if "help_card" in data:
            return evaluate_help_card(data["help_card"])
        return EvaluationResult(passed=True, quality_score=1.0, score=1.0)


def _merge_results(*results: EvaluationResult) -> EvaluationResult:
    errors = list(dict.fromkeys(error for result in results for error in result.errors))
    warnings = list(dict.fromkeys(warning for result in results for warning in result.warnings))
    metadata: dict[str, Any] = {}
    for result in results:
        metadata.update(result.metadata)
    return _result(errors=errors, warnings=warnings, metadata=metadata)


def _result(
    *,
    errors: list[str],
    warnings: list[str],
    metadata: dict[str, Any] | None = None,
) -> EvaluationResult:
    passed = not errors
    if errors:
        score = 0.0
        reason = "; ".join(errors)
        suggested_next_action: SuggestedNextAction = "retry_tool"
    elif warnings:
        score = 0.85
        reason = "; ".join(warnings)
        suggested_next_action = "continue"
    else:
        score = 1.0
        reason = "passed"
        suggested_next_action = "continue"
    return EvaluationResult(
        passed=passed,
        quality_score=score,
        score=score,
        issues=errors,
        errors=errors,
        warnings=warnings,
        reason=reason,
        suggested_next_action=suggested_next_action,
        metadata=metadata or {},
    )


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dumped
    if hasattr(value, "__dict__"):
        return {
            key: item
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return None


def _mapping_payload(tool_data: Mapping[str, Any], tool_result: Any) -> Mapping[str, Any]:
    for key in ("data", "output", "result"):
        payload = _as_mapping(tool_data.get(key))
        if payload is not None:
            return payload
    for key in ("data", "output", "result"):
        payload = _as_mapping(getattr(tool_result, key, None))
        if payload is not None:
            return payload
    return {}


def _titles_from_item(value: Any) -> list[str]:
    if isinstance(value, str):
        title = _clean_text(value)
        return [title] if title else []
    item = _as_mapping(value)
    if item is None:
        return []
    title = _clean_text(item.get("title"))
    return [title] if title else []


def _decision_factor_text(value: Any) -> str:
    if isinstance(value, str):
        return _clean_text(value)
    decision_factor = _as_mapping(value)
    if decision_factor is None:
        return ""
    return _clean_text(decision_factor.get("text"))


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = _clean_text(value)
        return [cleaned] if cleaned else []
    if isinstance(value, Sequence):
        return [cleaned for item in value if (cleaned := _clean_text(item))]
    return []


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_for_compare(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _compact_text(value: str) -> str:
    return re.sub(r"[\s,.;:!?，。；：！？、（）()【】\[\]《》\"'`]+", "", value).casefold()


def _is_generic_title(value: str) -> bool:
    compact = _compact_text(value)
    if compact in {_compact_text(item) for item in GENERIC_HELP_TITLES}:
        return True
    remaining = compact
    for part in _GENERIC_TITLE_PARTS:
        remaining = remaining.replace(_compact_text(part), "")
    return not remaining


def _is_generic_want(value: str) -> bool:
    return _compact_text(value) in {_compact_text(item) for item in GENERIC_WANTS}


def _is_generic_avoid(value: str) -> bool:
    return _compact_text(value) in {_compact_text(item) for item in GENERIC_AVOIDS}


def _is_generic_context(value: Any) -> bool:
    values = _context_text_values(value)
    if not values:
        return True

    combined = " ".join(values)
    compact = _compact_text(combined)
    generic_compacts = {
        _compact_text(item)
        for item in [*GENERIC_CONTEXTS, *GENERIC_WANTS, *GENERIC_AVOIDS, *GENERIC_HELP_TITLES]
    }
    if compact in generic_compacts:
        return True

    mapping = _as_mapping(value)
    if mapping is not None:
        nonempty_keys = {
            str(key)
            for key, item in mapping.items()
            if _has_nonempty_context(item)
        }
        normalized_keys = {key.lower() for key in nonempty_keys}
        if normalized_keys and normalized_keys <= _CONTEXT_LOCATION_ONLY_KEYS:
            return True
        if normalized_keys & _CONTEXT_DETAIL_KEYS:
            return False

    if _compact_text(combined) in {_compact_text(item) for item in GENERIC_CONTEXTS}:
        return True
    if len(compact) <= 4:
        return True
    if any(marker in combined for marker in _SPECIFIC_CONTEXT_MARKERS):
        return False
    return all(
        _is_generic_want(value_text)
        or _is_generic_avoid(value_text)
        or _is_generic_title(value_text)
        for value_text in values
    )


def _context_text_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = _clean_text(value)
        return [cleaned] if cleaned else []
    if isinstance(value, Mapping):
        values: list[str] = []
        for item in value.values():
            values.extend(_context_text_values(item))
        return values
    if isinstance(value, Sequence) and not isinstance(value, str):
        values: list[str] = []
        for item in value:
            values.extend(_context_text_values(item))
        return values
    cleaned = _clean_text(value)
    return [cleaned] if cleaned else []


def _has_evidence_reference(data: Mapping[str, Any]) -> bool:
    if _string_list(data.get("evidence_ids")):
        return True
    for key in ("retrieval_run_id", "intent_answer_id", "source_answer_id", "answer_id"):
        if _clean_text(data.get(key)):
            return True
    for nested_key in ("provenance", "metadata"):
        nested = _as_mapping(data.get(nested_key))
        if nested is not None and _has_evidence_reference(nested):
            return True
    return False


def _image_asset_quality(data: Mapping[str, Any]) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    metadata: dict[str, Any] = {}

    image_asset = _as_mapping(data.get("image_asset")) or _as_mapping(data.get("image"))
    image_asset_id = _clean_text(data.get("image_asset_id"))
    image_required = bool(data.get("image_required"))

    if image_required and image_asset is None and not image_asset_id:
        errors.append("recommendation_card_missing_required_image_asset")
        return errors, warnings, metadata

    if image_asset is None:
        if image_asset_id:
            metadata["image_asset_id"] = image_asset_id
        return errors, warnings, metadata

    resolved_id = _clean_text(image_asset.get("id") or image_asset_id)
    if not resolved_id:
        errors.append("recommendation_card_image_asset_missing_id")
    else:
        metadata["image_asset_id"] = resolved_id

    verified = bool(
        image_asset.get("verified")
        or image_asset.get("is_verified")
        or image_asset.get("verification_status") == "verified"
    )
    displayable = image_asset.get("displayable")
    is_ai_generated = bool(image_asset.get("is_ai_generated"))
    source_url = _clean_text(image_asset.get("source_url"))
    source_domain = _clean_text(image_asset.get("source_domain"))
    if not verified:
        errors.append("recommendation_card_image_asset_not_verified")
    if displayable is not True:
        errors.append("recommendation_card_image_asset_not_displayable")
    if is_ai_generated:
        errors.append("recommendation_card_image_asset_ai_generated")
    if not source_url:
        errors.append("recommendation_card_image_asset_missing_source_url")
    if not source_domain:
        errors.append("recommendation_card_image_asset_missing_source_domain")
    if verified and displayable is True and not is_ai_generated and source_url and source_domain:
        metadata["image_asset_verified_non_ai"] = True
    return errors, warnings, metadata


def _has_nonempty_context(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return any(_has_nonempty_context(item) for item in value.values())
    if isinstance(value, Sequence):
        return any(_has_nonempty_context(item) for item in value)
    return True


def _extract_recommendation_card(response: Mapping[str, Any]) -> Mapping[str, Any] | None:
    data = _as_mapping(response.get("data"))
    if data is not None:
        card = _as_mapping(data.get("recommendation_card"))
        if card is not None:
            return card
        card = _as_mapping(data.get("card"))
        if card is not None:
            return card

    card = _as_mapping(response.get("recommendation_card"))
    if card is not None:
        return card

    if _looks_like_recommendation_card(response):
        return response

    cards = response.get("cards")
    if isinstance(cards, Sequence) and not isinstance(cards, str):
        for item in cards:
            card = _as_mapping(item)
            if card is not None:
                return card

    ui_events = response.get("ui_events")
    if isinstance(ui_events, Sequence) and not isinstance(ui_events, str):
        for event in ui_events:
            event_data = _as_mapping(event)
            if event_data is None:
                continue
            card = _as_mapping(event_data.get("recommendation_card")) or _as_mapping(
                event_data.get("card")
            )
            if card is not None:
                return card
    return None


def _extract_help_card(response: Mapping[str, Any]) -> Mapping[str, Any] | None:
    data = _as_mapping(response.get("data"))
    if data is not None:
        help_card = _as_mapping(data.get("help_card"))
        if help_card is not None:
            return help_card

    help_card = _as_mapping(response.get("help_card"))
    if help_card is not None:
        return help_card

    help_cards = response.get("help_cards")
    if isinstance(help_cards, Sequence) and not isinstance(help_cards, str):
        for item in help_cards:
            help_card = _as_mapping(item)
            if help_card is not None:
                return help_card

    ui_events = response.get("ui_events")
    if isinstance(ui_events, Sequence) and not isinstance(ui_events, str):
        for event in ui_events:
            event_data = _as_mapping(event)
            if event_data is None:
                continue
            help_card = _as_mapping(event_data.get("help_card"))
            if help_card is not None:
                return help_card
    return None


def _looks_like_recommendation_card(value: Mapping[str, Any]) -> bool:
    return bool(
        value.get("target_type")
        or value.get("decision_factor")
        or value.get("item")
        or value.get("items")
    ) and bool(value.get("title") or value.get("item") or value.get("items"))


def _is_haidilao_venue_order_request(message: str) -> bool:
    normalized = message.casefold()
    if not any(alias.casefold() in normalized for alias in HAIDILAO_ALIASES):
        return False
    if any(hint in message for hint in NOT_IN_VENUE_HINTS):
        return False
    has_ordering = any(hint in message for hint in VENUE_ORDERING_HINTS)
    has_presence = any(hint in message for hint in VENUE_PRESENCE_HINTS)
    return has_ordering or has_presence
