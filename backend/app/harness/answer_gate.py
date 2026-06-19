"""Answer-level guardrails for deterministic Pipi harnesses."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.harness.evaluator import EvaluationResult


_MISSING = object()
_FORBIDDEN_UI_EVENT_COPY_FIELDS = {
    "body",
    "button_text",
    "caption",
    "copy",
    "description",
    "label",
    "message",
    "one_liner",
    "subtitle",
    "text",
    "title",
    "toast",
}
_FORBIDDEN_ANSWER_COPY_PATTERNS = (
    re.compile(r"\bui_events?\b", re.IGNORECASE),
    re.compile(r"\bshow_(?:recommendation|help)_card\b", re.IGNORECASE),
    re.compile(r"\bhelp_card_(?:draft|published|updated)\b", re.IGNORECASE),
    re.compile(r"\b(?:debug|trace|runtime|fallback|schema|provider|model)\b", re.IGNORECASE),
    re.compile(r"(调试|链路|内部|运行时|兜底|模型适配器)"),
    re.compile(r"(没有|无|缺少|不可用).{0,8}(工具|tool)"),
    re.compile(r"(工具|tool).{0,8}(不可用|失败|没跑通|不能用|调用失败)"),
    re.compile(r"(调用|执行).{0,8}(工具|tool)"),
    re.compile(r"(推荐卡|卡片|界面|按钮|UI)"),
    re.compile(r"(已|已经|我会|我给你|为你).{0,8}(展示|生成|弹出|打开).{0,8}(卡|卡片|按钮)"),
)


@dataclass
class _KnownArtifacts:
    recommendation_card_ids: set[str] = field(default_factory=set)
    help_card_ids: set[str] = field(default_factory=set)
    light_event_ids: set[str] = field(default_factory=set)
    tool_recommendation_card_ids: set[str] = field(default_factory=set)
    tool_help_card_ids: set[str] = field(default_factory=set)
    tool_light_event_ids: set[str] = field(default_factory=set)
    tool_names: set[str] = field(default_factory=set)

    def merge(self, other: "_KnownArtifacts") -> None:
        self.recommendation_card_ids.update(other.recommendation_card_ids)
        self.help_card_ids.update(other.help_card_ids)
        self.light_event_ids.update(other.light_event_ids)
        self.tool_recommendation_card_ids.update(other.tool_recommendation_card_ids)
        self.tool_help_card_ids.update(other.tool_help_card_ids)
        self.tool_light_event_ids.update(other.tool_light_event_ids)
        self.tool_names.update(other.tool_names)


class AnswerGateResult(EvaluationResult):
    """Compatibility alias with the shared evaluation result fields."""


class AnswerGate:
    """Reject answers that bypass tools by embedding unpersisted card JSON."""

    def __init__(
        self,
        persisted_card_ids: Iterable[str] | None = None,
        persisted_help_card_ids: Iterable[str] | None = None,
    ) -> None:
        self.persisted_card_ids = _id_set(persisted_card_ids)
        self.persisted_help_card_ids = _id_set(persisted_help_card_ids)

    def validate(
        self_or_answer: Any = _MISSING,
        answer: Any = _MISSING,
        decision: Any = _MISSING,
        *,
        persisted_card_ids: Iterable[str] | None = None,
        persisted_help_card_ids: Iterable[str] | None = None,
    ) -> AnswerGateResult:
        """Validate either a raw answer or a `(state, decision)` harness pair."""

        state: Any = None
        known_ids = _id_set(persisted_card_ids)
        known_help_ids = _id_set(persisted_help_card_ids)

        if isinstance(self_or_answer, AnswerGate):
            known_ids.update(self_or_answer.persisted_card_ids)
            known_help_ids.update(self_or_answer.persisted_help_card_ids)
            if decision is not _MISSING:
                state = answer
                value = decision
            elif answer is not _MISSING:
                value = answer
            else:
                value = ""
        elif decision is not _MISSING:
            state = self_or_answer
            value = decision
        elif self_or_answer is _MISSING and answer is not _MISSING:
            value = answer
        elif answer is _MISSING:
            value = self_or_answer
        else:
            value = answer

        errors: list[str] = []
        metadata: dict[str, Any] = {"checked_paths": []}
        artifacts = _KnownArtifacts(
            recommendation_card_ids=set(known_ids),
            help_card_ids=set(known_help_ids),
        )

        if state is not None:
            artifacts.merge(_collect_known_artifacts(state))
        artifacts.merge(_collect_known_artifacts(value))
        metadata["known_artifacts"] = {
            "recommendation_card_ids": sorted(artifacts.recommendation_card_ids),
            "help_card_ids": sorted(artifacts.help_card_ids),
            "light_event_ids": sorted(artifacts.light_event_ids),
            "tool_recommendation_card_ids": sorted(artifacts.tool_recommendation_card_ids),
            "tool_help_card_ids": sorted(artifacts.tool_help_card_ids),
            "tool_light_event_ids": sorted(artifacts.tool_light_event_ids),
            "tool_names": sorted(artifacts.tool_names),
        }

        errors.extend(_state_decision_issues(state, value, artifacts))

        for path, node in _walk_jsonlike_values(value):
            if _is_card_payload(node):
                metadata["checked_paths"].append(path)
                if not _has_persisted_card_identity(node, artifacts.recommendation_card_ids):
                    errors.append(f"answer_contains_unpersisted_card_json:{path}")
                if not _has_persisted_card_identity(node, artifacts.tool_recommendation_card_ids):
                    errors.append(f"answer_contains_card_json_not_from_tool:{path}")
            elif _is_help_card_payload(node):
                metadata["checked_paths"].append(path)
                if not _has_persisted_help_card_identity(node, artifacts.help_card_ids):
                    errors.append(f"answer_contains_unpersisted_help_card_json:{path}")
                if not _has_persisted_help_card_identity(node, artifacts.tool_help_card_ids):
                    errors.append(f"answer_contains_help_card_json_not_from_tool:{path}")

        if isinstance(value, str):
            parsed_fragments = list(_json_values_from_text(value))
            for index, fragment in enumerate(parsed_fragments):
                for path, node in _walk_jsonlike_values(fragment, path=f"$json[{index}]"):
                    if _is_card_payload(node):
                        metadata["checked_paths"].append(path)
                        if not _has_persisted_card_identity(
                            node,
                            artifacts.recommendation_card_ids,
                        ):
                            errors.append(f"answer_contains_unpersisted_card_json:{path}")
                        if not _has_persisted_card_identity(
                            node,
                            artifacts.tool_recommendation_card_ids,
                        ):
                            errors.append(f"answer_contains_card_json_not_from_tool:{path}")
                    elif _is_help_card_payload(node):
                        metadata["checked_paths"].append(path)
                        if not _has_persisted_help_card_identity(
                            node,
                            artifacts.help_card_ids,
                        ):
                            errors.append(f"answer_contains_unpersisted_help_card_json:{path}")
                        if not _has_persisted_help_card_identity(
                            node,
                            artifacts.tool_help_card_ids,
                        ):
                            errors.append(f"answer_contains_help_card_json_not_from_tool:{path}")
            if not parsed_fragments and _looks_like_raw_unpersisted_card_json(value):
                errors.append("answer_contains_unpersisted_card_json:$text")
            if not parsed_fragments and _looks_like_raw_unpersisted_help_card_json(value):
                errors.append("answer_contains_unpersisted_help_card_json:$text")

        unique_errors = list(dict.fromkeys(errors))
        passed = not unique_errors
        return AnswerGateResult(
            passed=passed,
            quality_score=1.0 if passed else 0.0,
            score=1.0 if passed else 0.0,
            issues=unique_errors,
            errors=unique_errors,
            reason="passed" if passed else "; ".join(unique_errors),
            suggested_next_action="continue" if passed else "answer_safe",
            metadata=metadata,
        )


def _state_decision_issues(
    state: Any,
    decision: Any,
    artifacts: _KnownArtifacts,
) -> list[str]:
    issues: list[str] = []
    message = decision if isinstance(decision, str) else _value(decision, "message")
    if _contains_forbidden_ui_copy(_nonempty_text(message)):
        issues.append("answer_contains_forbidden_ui_copy")

    ui_events = _sequence_value(_value(decision, "ui_events"))
    intent = _intent_value(state, decision)

    if intent in {"greeting", "smalltalk", "app_help", "unknown"} and ui_events:
        issues.append("non_task_answer_has_ui_events")

    for card in _recommendation_cards_from_decision(decision):
        if not _card_from_known_tool(card, artifacts.tool_recommendation_card_ids):
            issues.append("recommendation_card_not_from_tool")

    for help_card in _help_cards_from_decision(decision):
        if not _help_card_from_known_tool(help_card, artifacts.tool_help_card_ids):
            issues.append("help_card_not_from_tool")

    for event in ui_events:
        if not isinstance(event, Mapping):
            issues.append("invalid_ui_event")
            continue
        if _ui_event_has_forbidden_copy(event):
            issues.append("ui_event_contains_forbidden_copy")
        event_type = str(event.get("type") or "")
        if event_type == "show_recommendation_card":
            card_id = _nonempty_text(event.get("card_id") or event.get("recommendation_card_id"))
            if not card_id:
                issues.append("missing_card_id")
            elif card_id not in artifacts.recommendation_card_ids:
                issues.append("ui_event_card_id_not_persisted")
            if card_id and card_id not in artifacts.tool_recommendation_card_ids:
                issues.append("recommendation_card_not_from_tool")
                issues.append("ui_event_card_id_not_from_tool")
            embedded_card = _mapping_value(
                event.get("recommendation_card") or event.get("card")
            )
            embedded_id = _first_text(
                embedded_card.get("id"),
                embedded_card.get("card_id"),
                embedded_card.get("recommendation_card_id"),
            )
            if embedded_id and card_id and embedded_id != card_id:
                issues.append("ui_event_card_id_mismatch")
        elif event_type in {"show_help_card_draft", "help_card_updated", "help_card_published"}:
            help_card_id = _nonempty_text(event.get("help_card_id") or event.get("help_request_id"))
            if not help_card_id:
                issues.append("missing_help_card_id")
            elif help_card_id not in artifacts.help_card_ids:
                issues.append("ui_event_help_card_id_not_persisted")
            if help_card_id and help_card_id not in artifacts.tool_help_card_ids:
                issues.append("help_card_not_from_tool")
                issues.append("ui_event_help_card_id_not_from_tool")
            embedded_help_card = _mapping_value(event.get("help_card"))
            embedded_id = _first_text(
                embedded_help_card.get("id"),
                embedded_help_card.get("help_card_id"),
                embedded_help_card.get("help_request_id"),
            )
            if embedded_id and help_card_id and embedded_id != help_card_id:
                issues.append("ui_event_help_card_id_mismatch")
        elif "light" in event_type:
            light_event_id = _nonempty_text(event.get("light_event_id") or event.get("id"))
            if not light_event_id:
                issues.append("missing_light_event_id")
            elif artifacts.light_event_ids and light_event_id not in artifacts.light_event_ids:
                issues.append("ui_event_light_event_id_not_persisted")
            if light_event_id and light_event_id not in artifacts.tool_light_event_ids:
                issues.append("ui_event_light_event_id_not_from_tool")
    return issues


def _walk_jsonlike_values(value: Any, path: str = "$") -> Iterable[tuple[str, Mapping[str, Any]]]:
    if isinstance(value, Mapping):
        yield path, value
        for key, item in value.items():
            yield from _walk_jsonlike_values(item, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, str):
        for index, item in enumerate(value):
            yield from _walk_jsonlike_values(item, f"{path}[{index}]")
    else:
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            yield from _walk_jsonlike_values(model_dump(mode="json"), path)


def _is_card_payload(value: Mapping[str, Any]) -> bool:
    has_decision = "decision_factor" in value or "decision_factors" in value
    return has_decision and _has_title_signal(value)


def _is_help_card_payload(value: Mapping[str, Any]) -> bool:
    if str(value.get("type") or "") == "help_card":
        return True
    has_help_shape = (
        "wants" in value
        or "avoids" in value
        or "constraints" in value
        or "prompt" in value
        or "context" in value
    )
    has_help_identity = bool(
        value.get("help_card_id") or value.get("help_request_id")
    )
    return (has_help_shape or has_help_identity) and (
        _nonempty_text(value.get("title"))
        or _nonempty_text(value.get("prompt"))
        or bool(_mapping_value(value.get("context")))
    )


def _has_title_signal(value: Mapping[str, Any]) -> bool:
    if _nonempty_text(value.get("title")):
        return True
    item = value.get("item")
    if isinstance(item, str) and item.strip():
        return True
    if isinstance(item, Mapping) and _nonempty_text(item.get("title")):
        return True
    items = value.get("items")
    if isinstance(items, Sequence) and not isinstance(items, str):
        return any(
            _has_title_signal(item) if isinstance(item, Mapping) else bool(str(item).strip())
            for item in items
        )
    return False


def _has_persisted_card_identity(
    value: Mapping[str, Any],
    persisted_card_ids: set[str],
) -> bool:
    identities = [
        value.get("id"),
        value.get("card_id"),
        value.get("recommendation_card_id"),
    ]
    for identity in identities:
        text = _nonempty_text(identity)
        if not text:
            continue
        if text in persisted_card_ids:
            return True
    return False


def _has_persisted_help_card_identity(
    value: Mapping[str, Any],
    persisted_help_card_ids: set[str],
) -> bool:
    identities = [
        value.get("id"),
        value.get("help_card_id"),
        value.get("help_request_id"),
    ]
    for identity in identities:
        text = _nonempty_text(identity)
        if not text:
            continue
        if text in persisted_help_card_ids:
            return True
    return False


def _json_values_from_text(text: str) -> Iterable[Any]:
    stripped = text.strip()
    if not stripped:
        return

    try:
        yield json.loads(stripped)
        return
    except json.JSONDecodeError:
        pass

    for block in re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL):
        try:
            yield json.loads(block.strip())
        except json.JSONDecodeError:
            continue

    for fragment in _balanced_json_fragments(text):
        try:
            yield json.loads(fragment)
        except json.JSONDecodeError:
            continue


def _balanced_json_fragments(text: str) -> Iterable[str]:
    start: int | None = None
    stack: list[str] = []
    in_string = False
    escape = False
    pairs = {"}": "{", "]": "["}
    openings = set(pairs.values())

    for index, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char in openings:
            if not stack:
                start = index
            stack.append(char)
            continue
        if char in pairs and stack:
            if stack[-1] != pairs[char]:
                stack.clear()
                start = None
                continue
            stack.pop()
            if not stack and start is not None:
                yield text[start : index + 1]
                start = None


_RAW_DECISION_KEY_RE = re.compile(r"['\"]decision_factors?['\"]")
_RAW_TITLE_KEY_RE = re.compile(r"['\"](?:title|item|items)['\"]")
_RAW_ID_KEY_RE = re.compile(r"['\"](?:id|card_id|recommendation_card_id)['\"]")
_RAW_HELP_KEY_RE = re.compile(r"['\"](?:help_card_id|prompt|wants|avoids|context)['\"]")
_RAW_HELP_ID_KEY_RE = re.compile(r"['\"](?:id|help_card_id|help_request_id)['\"]")


def _looks_like_raw_unpersisted_card_json(text: str) -> bool:
    return (
        bool(_RAW_DECISION_KEY_RE.search(text))
        and bool(_RAW_TITLE_KEY_RE.search(text))
        and not bool(_RAW_ID_KEY_RE.search(text))
    )


def _looks_like_raw_unpersisted_help_card_json(text: str) -> bool:
    return bool(_RAW_HELP_KEY_RE.search(text)) and not bool(_RAW_HELP_ID_KEY_RE.search(text))


def _contains_forbidden_ui_copy(text: str) -> bool:
    if not text:
        return False
    return any(pattern.search(text) for pattern in _FORBIDDEN_ANSWER_COPY_PATTERNS)


def _ui_event_has_forbidden_copy(event: Mapping[str, Any]) -> bool:
    for copy_field in _FORBIDDEN_UI_EVENT_COPY_FIELDS:
        if _nonempty_text(event.get(copy_field)):
            return True
    return False


def _state_value(state: Any, key: str) -> Any:
    if state is None:
        return None
    direct = _value(state, key)
    if direct is not None:
        return direct
    metadata = _mapping_value(_value(state, "metadata"))
    return metadata.get(key)


def _intent_value(state: Any, decision: Any) -> str:
    for source in (state, decision):
        for key in ("intent", "intent_type"):
            value = _state_value(source, key)
            if value:
                return str(value)
    return ""


def _value(obj: Any, key: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key)
    return getattr(obj, key, None)


def _mapping_value(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _recommendation_cards_from_decision(decision: Any) -> list[Mapping[str, Any]]:
    cards: list[Mapping[str, Any]] = []
    data = _mapping_value(_value(decision, "data"))
    for key in ("recommendation_card", "card"):
        card = _mapping_value(data.get(key))
        if card:
            cards.append(card)
    top_card = _mapping_value(_value(decision, "recommendation_card"))
    if top_card:
        cards.append(top_card)
    for item in _sequence_value(_value(decision, "cards")):
        card = _mapping_value(item)
        if card:
            cards.append(card)
    return cards


def _help_cards_from_decision(decision: Any) -> list[Mapping[str, Any]]:
    help_cards: list[Mapping[str, Any]] = []
    data = _mapping_value(_value(decision, "data"))
    help_card = _mapping_value(data.get("help_card"))
    if help_card:
        help_cards.append(help_card)
    top_help_card = _mapping_value(_value(decision, "help_card"))
    if top_help_card:
        help_cards.append(top_help_card)
    for item in _sequence_value(_value(decision, "help_cards")):
        help_card = _mapping_value(item)
        if help_card:
            help_cards.append(help_card)
    return help_cards


def _card_from_known_tool(card: Mapping[str, Any], known_ids: set[str]) -> bool:
    identities = _identity_set(
        card,
        keys=("id", "card_id", "recommendation_card_id"),
    )
    return bool(identities and identities & known_ids)


def _help_card_from_known_tool(help_card: Mapping[str, Any], known_ids: set[str]) -> bool:
    identities = _identity_set(
        help_card,
        keys=("id", "help_card_id", "help_request_id"),
    )
    return bool(identities and identities & known_ids)


def _collect_known_artifacts(value: Any) -> _KnownArtifacts:
    artifacts = _KnownArtifacts()
    if value is None or value is _MISSING:
        return artifacts

    mapping = _model_mapping(value)
    if mapping is None:
        return artifacts

    for key in ("tool_results", "tool_calls"):
        for item in _sequence_value(mapping.get(key)):
            _collect_tool_artifact_from_entry(item, artifacts)

    if _looks_like_tool_entry(mapping):
        _collect_tool_artifact_from_entry(mapping, artifacts)

    trace = mapping.get("trace")
    for event in _sequence_value(trace):
        event_mapping = _model_mapping(event)
        if event_mapping is None:
            continue
        payload = event_mapping.get("payload") or event_mapping.get("data")
        if event_mapping.get("event") in {"tool_result", "tool_call"}:
            _collect_tool_artifact_from_entry(payload, artifacts)
    return artifacts


def _collect_tool_artifact_from_entry(entry: Any, artifacts: _KnownArtifacts) -> None:
    mapping = _model_mapping(entry)
    if mapping is None:
        return

    decision = _mapping_value(mapping.get("decision"))
    tool_result = _mapping_value(mapping.get("tool_result"))
    tool_call = _mapping_value(mapping.get("tool_call"))

    tool_name = _first_text(
        mapping.get("tool_name"),
        mapping.get("name"),
        decision.get("tool_name"),
        decision.get("name"),
        tool_result.get("tool_name"),
        tool_result.get("name"),
        tool_call.get("tool_name"),
        tool_call.get("name"),
    )
    if tool_name:
        artifacts.tool_names.add(tool_name)

    payloads = [
        mapping,
        tool_result,
        tool_call,
        _mapping_value(mapping.get("data")),
        _mapping_value(mapping.get("output")),
        _mapping_value(mapping.get("result")),
        _mapping_value(tool_result.get("data")),
        _mapping_value(tool_result.get("output")),
        _mapping_value(tool_result.get("result")),
        _mapping_value(tool_call.get("data")),
        _mapping_value(tool_call.get("output")),
        _mapping_value(tool_call.get("result")),
    ]

    for payload in payloads:
        if not payload:
            continue
        if tool_name in {"create_recommendation_card", "finalize_help_card"}:
            ids = _recommendation_card_ids(payload)
            artifacts.recommendation_card_ids.update(ids)
            artifacts.tool_recommendation_card_ids.update(ids)
        elif tool_name in {
            "draft_help_card",
            "update_help_card",
            "publish_help_card",
            "submit_one_liner_answer",
        }:
            ids = _help_card_ids(payload)
            artifacts.help_card_ids.update(ids)
            artifacts.tool_help_card_ids.update(ids)
        elif tool_name == "light_user":
            ids = _light_event_ids(payload)
            artifacts.light_event_ids.update(ids)
            artifacts.tool_light_event_ids.update(ids)

    if not tool_name:
        for payload in payloads:
            if not payload:
                continue
            recommendation_ids = _recommendation_card_ids(payload)
            help_ids = _help_card_ids(payload)
            light_ids = _light_event_ids(payload)
            artifacts.recommendation_card_ids.update(recommendation_ids)
            artifacts.help_card_ids.update(help_ids)
            artifacts.light_event_ids.update(light_ids)
            artifacts.tool_recommendation_card_ids.update(recommendation_ids)
            artifacts.tool_help_card_ids.update(help_ids)
            artifacts.tool_light_event_ids.update(light_ids)


def _recommendation_card_ids(payload: Mapping[str, Any]) -> set[str]:
    ids = _identity_set(payload, keys=("id", "card_id", "recommendation_card_id", "final_card_id"))
    card = _mapping_value(payload.get("recommendation_card") or payload.get("card"))
    ids.update(_identity_set(card, keys=("id", "card_id", "recommendation_card_id")))
    return ids


def _help_card_ids(payload: Mapping[str, Any]) -> set[str]:
    ids = _identity_set(payload, keys=("id", "help_card_id", "help_request_id"))
    help_card = _mapping_value(payload.get("help_card"))
    ids.update(_identity_set(help_card, keys=("id", "help_card_id", "help_request_id")))
    return ids


def _light_event_ids(payload: Mapping[str, Any]) -> set[str]:
    ids = _identity_set(payload, keys=("light_event_id", "id"))
    light_event = _mapping_value(payload.get("light_event"))
    ids.update(_identity_set(light_event, keys=("id", "light_event_id")))
    return ids


def _identity_set(payload: Mapping[str, Any], *, keys: tuple[str, ...]) -> set[str]:
    return {text for key in keys if (text := _nonempty_text(payload.get(key)))}


def _first_text(*values: Any) -> str:
    for value in values:
        text = _nonempty_text(value)
        if text:
            return text
    return ""


def _sequence_value(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, str):
        return list(value)
    return []


def _model_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dumped
    return None


def _looks_like_tool_entry(value: Mapping[str, Any]) -> bool:
    return bool(
        value.get("tool_name")
        or value.get("name")
        or value.get("tool_result")
        or value.get("tool_call")
        or value.get("decision")
    )


def _nonempty_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _id_set(values: Iterable[str] | None) -> set[str]:
    if values is None:
        return set()
    return {text for value in values if (text := _nonempty_text(value))}
