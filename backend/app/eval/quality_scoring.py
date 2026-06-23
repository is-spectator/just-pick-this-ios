"""Deterministic quality scoring for pipi benchmark responses."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from app.harness.evaluator import evaluate_help_card, evaluate_recommendation_card


QUALITY_SCORE_VERSION = "pipi-quality-scoring-v1"
QUALITY_SCORE_FORMULA = "quality_score = max(0.0, 1.0 - sum(dimension_penalties.values()))"
QUALITY_DIMENSIONS = (
    "response_kind",
    "routing",
    "tool_call",
    "persistence",
    "card_contract",
    "evidence_safety",
    "help_card_specificity",
)
ResponseKind = Literal[
    "recommendation_card",
    "help_card_draft",
    "clarification",
    "chitchat",
    "unknown",
]
IssueSeverity = Literal["error", "warning"]
CaseStatus = Literal["passed", "degraded", "failed"]

_UI_EVENT_TO_KIND = {
    "show_recommendation_card": "recommendation_card",
    "show_help_card_draft": "help_card_draft",
}
_EXPECTED_TOOL_BY_KIND = {
    "recommendation_card": "create_recommendation_card",
    "help_card_draft": "draft_help_card",
}


@dataclass(frozen=True)
class QualityIssue:
    code: str
    severity: IssueSeverity
    penalty: float
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "penalty": self.penalty,
        }
        if self.message:
            payload["message"] = self.message
        if self.metadata:
            payload["metadata"] = self.metadata
        return payload


@dataclass(frozen=True)
class CaseQualityScore:
    case_id: str
    quality_score: float
    status: CaseStatus
    passed: bool
    expected_kind: str | None
    actual_kind: ResponseKind
    issues: list[QualityIssue] = field(default_factory=list)
    dimensions: dict[str, float] = field(default_factory=dict)
    dimension_penalties: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    scoring_version: str = QUALITY_SCORE_VERSION

    @property
    def errors(self) -> list[QualityIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[QualityIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "quality_score": self.quality_score,
            "status": self.status,
            "passed": self.passed,
            "expected_kind": self.expected_kind,
            "actual_kind": self.actual_kind,
            "issues": [issue.to_dict() for issue in self.issues],
            "errors": [issue.to_dict() for issue in self.errors],
            "warnings": [issue.to_dict() for issue in self.warnings],
            "dimensions": self.dimensions,
            "dimension_penalties": self.dimension_penalties,
            "metadata": self.metadata,
            "scoring_version": self.scoring_version,
        }


def score_rows(rows: Sequence[Mapping[str, Any]]) -> list[CaseQualityScore]:
    return [score_case_result(row) for row in rows]


def summarize_scores(scores: Sequence[CaseQualityScore]) -> dict[str, Any]:
    status_counts = Counter(score.status for score in scores)
    issue_counts = Counter(issue.code for score in scores for issue in score.issues)
    total = len(scores)
    passed = status_counts.get("passed", 0)
    degraded = status_counts.get("degraded", 0)
    failed = status_counts.get("failed", 0)
    average_score = sum(score.quality_score for score in scores) / total if total else 0.0
    return {
        "scoring_version": QUALITY_SCORE_VERSION,
        "score_formula": QUALITY_SCORE_FORMULA,
        "quality_dimensions": list(QUALITY_DIMENSIONS),
        "total": total,
        "passed": passed,
        "degraded": degraded,
        "failed": failed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "non_failed_rate": round((passed + degraded) / total, 4) if total else 0.0,
        "average_quality_score": round(average_score, 4),
        "average_dimensions": _average_dimensions(scores),
        "dimension_penalty_totals": _dimension_penalty_totals(scores),
        "status_counts": dict(status_counts),
        "issue_counts": dict(issue_counts),
        "top_issues": [
            {"code": code, "count": count}
            for code, count in issue_counts.most_common(20)
        ],
    }


def score_case_result(
    row_or_case: Mapping[str, Any],
    response: Mapping[str, Any] | None = None,
) -> CaseQualityScore:
    case, actual_response = _split_case_and_response(row_or_case, response)
    case_id = _case_id(case, row_or_case)
    expected = _expected(case)
    expected_kind = _expected_kind(expected, case)
    actual_kind = _actual_response_kind(actual_response)

    issues: list[QualityIssue] = []

    def add(
        code: str,
        *,
        severity: IssueSeverity,
        penalty: float,
        message: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        issues.append(
            QualityIssue(
                code=code,
                severity=severity,
                penalty=penalty,
                message=message,
                metadata=metadata or {},
            )
        )

    if actual_response is None:
        add(
            "response_missing",
            severity="error",
            penalty=1.0,
            message="Benchmark row has no backend response payload.",
        )
        return _finish_score(case_id, expected_kind, actual_kind, issues, case, actual_response)

    if expected_kind and expected_kind != actual_kind:
        allow_help_fallback = bool(
            expected.get("allow_help_card_fallback")
            or expected.get("allow_degraded_help_card")
            or case.get("allow_help_card_fallback")
        )
        if (
            expected_kind == "recommendation_card"
            and actual_kind == "help_card_draft"
            and allow_help_fallback
        ):
            add(
                "recommendation_degraded_to_help_card",
                severity="warning",
                penalty=0.25,
                message="Expected a recommendation card, but accepted help-card fallback.",
            )
        else:
            add(
                "response_kind_mismatch",
                severity="error",
                penalty=0.45,
                metadata={"expected": expected_kind, "actual": actual_kind},
            )

    expected_location_state = _first_text(
        expected.get("location_state"),
        case.get("expected_location_state"),
        case.get("location_state"),
    )
    actual_location_state = _actual_location_state(actual_response)
    if expected_location_state and actual_location_state != expected_location_state:
        add(
            "location_state_mismatch",
            severity="error",
            penalty=0.15,
            metadata={"expected": expected_location_state, "actual": actual_location_state},
        )

    if actual_kind == "recommendation_card":
        _score_recommendation_card(
            actual_response,
            expected=expected,
            add_issue=add,
        )
    elif actual_kind == "help_card_draft":
        _score_help_card(actual_response, add_issue=add)

    expected_tool = _expected_tool(expected, actual_kind, expected_kind)
    if expected_tool:
        tool_names = _tool_names(actual_response)
        if not tool_names:
            add(
                "tool_call_missing",
                severity="error",
                penalty=0.2,
                message="Card/help-card result must expose the tool call used to create it.",
            )
        elif expected_tool not in tool_names:
            add(
                "tool_call_name_mismatch",
                severity="error",
                penalty=0.15,
                metadata={"expected": expected_tool, "actual": sorted(tool_names)},
            )

    if _requires_retrieval(expected, actual_kind, expected_kind):
        if not _has_retrieval_run(actual_response):
            add(
                "retrieval_run_missing",
                severity="error",
                penalty=0.2,
                message="Benchmark response should carry a persisted retrieval_run id or object.",
            )

    if _requires_agent_run(expected, actual_kind, expected_kind):
        if not _has_agent_run(actual_response):
            add(
                "agent_run_id_missing",
                severity="warning",
                penalty=0.05,
                message="Response is missing agent_run_id in metadata/debug.",
            )

    return _finish_score(case_id, expected_kind, actual_kind, issues, case, actual_response)


def _score_recommendation_card(
    response: Mapping[str, Any],
    *,
    expected: Mapping[str, Any],
    add_issue: Any,
) -> None:
    card = _recommendation_card(response)
    if card is None:
        add_issue(
            "recommendation_card_missing",
            severity="error",
            penalty=0.35,
        )
        return

    evaluator_result = evaluate_recommendation_card(card)
    for code in evaluator_result.errors:
        add_issue(
            code,
            severity="error",
            penalty=0.12,
        )
    for code in evaluator_result.warnings:
        add_issue(
            code,
            severity="warning",
            penalty=0.04,
        )

    expected_target_type = _first_text(expected.get("target_type"), expected.get("card_target_type"))
    actual_target_type = _first_text(card.get("target_type"), _mapping(card.get("item")).get("category"))
    if expected_target_type and actual_target_type != expected_target_type:
        add_issue(
            "target_type_mismatch",
            severity="error",
            penalty=0.15,
            metadata={"expected": expected_target_type, "actual": actual_target_type},
        )

    requires_trusted_image = expected.get("requires_verified_image")
    if requires_trusted_image is None:
        requires_trusted_image = False
    if requires_trusted_image and not _has_trusted_image_or_place(card):
        add_issue(
            "recommendation_card_missing_trusted_image_or_place",
            severity="error",
            penalty=0.2,
            message=(
                "Recommendation cards need a verified non-AI image, or an AMap place/action "
                "exception."
            ),
        )

    if not _has_recommendation_evidence(card):
        add_issue(
            "recommendation_card_missing_evidence",
            severity="error",
            penalty=0.15,
        )


def _score_help_card(response: Mapping[str, Any], *, add_issue: Any) -> None:
    help_card = _help_card(response)
    if help_card is None:
        add_issue("help_card_missing", severity="error", penalty=0.35)
        return

    evaluator_result = evaluate_help_card(help_card)
    for code in evaluator_result.errors:
        add_issue(code, severity="error", penalty=0.15)
    for code in evaluator_result.warnings:
        add_issue(code, severity="warning", penalty=0.04)

    context = help_card.get("context")
    if not _non_empty_value(context):
        add_issue(
            "help_card_missing_context",
            severity="error",
            penalty=0.12,
        )


def _finish_score(
    case_id: str,
    expected_kind: str | None,
    actual_kind: ResponseKind,
    issues: list[QualityIssue],
    case: Mapping[str, Any],
    response: Mapping[str, Any] | None,
) -> CaseQualityScore:
    dimension_penalties = _dimension_penalties(issues)
    penalty = sum(dimension_penalties.values())
    quality_score = max(0.0, round(1.0 - penalty, 4))
    dimensions = {
        dimension: max(0.0, round(1.0 - dimension_penalties.get(dimension, 0.0), 4))
        for dimension in QUALITY_DIMENSIONS
    }
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        status: CaseStatus = "failed"
    elif issues:
        status = "degraded"
    else:
        status = "passed"

    return CaseQualityScore(
        case_id=case_id,
        quality_score=quality_score,
        status=status,
        passed=status == "passed",
        expected_kind=expected_kind,
        actual_kind=actual_kind,
        issues=issues,
        dimensions=dimensions,
        dimension_penalties=dimension_penalties,
        metadata={
            "message": _first_text(case.get("message"), case.get("input")),
            "category": _first_text(case.get("category"), case.get("group")),
            "latency_ms": _first_number(
                _mapping(response).get("latency_ms"),
                case.get("latency_ms"),
            ),
            "trace_id": _trace_id(response),
            "agent_run_id": _agent_run_id(response),
            "retrieval_run_id": _retrieval_run_id(response),
            "score_formula": QUALITY_SCORE_FORMULA,
        },
    )


def _dimension_penalties(issues: Sequence[QualityIssue]) -> dict[str, float]:
    penalties = {dimension: 0.0 for dimension in QUALITY_DIMENSIONS}
    for issue in issues:
        dimension = _issue_dimension(issue.code)
        penalties[dimension] += issue.penalty
    return {
        dimension: round(penalty, 4)
        for dimension, penalty in penalties.items()
        if penalty > 0
    }


def _issue_dimension(code: str) -> str:
    if code in {"response_missing", "response_kind_mismatch", "recommendation_degraded_to_help_card"}:
        return "response_kind"
    if code in {"location_state_mismatch", "target_type_mismatch"} or code.startswith("venue_order_"):
        return "routing"
    if code.startswith("tool_call_"):
        return "tool_call"
    if code in {"retrieval_run_missing", "agent_run_id_missing"}:
        return "persistence"
    if code.startswith("help_card_"):
        return "help_card_specificity"
    if "image" in code or "evidence" in code:
        return "evidence_safety"
    if code.startswith("recommendation_card_"):
        return "card_contract"
    return "card_contract"


def _average_dimensions(scores: Sequence[CaseQualityScore]) -> dict[str, float]:
    if not scores:
        return {dimension: 0.0 for dimension in QUALITY_DIMENSIONS}
    return {
        dimension: round(
            sum(score.dimensions.get(dimension, 1.0) for score in scores) / len(scores),
            4,
        )
        for dimension in QUALITY_DIMENSIONS
    }


def _dimension_penalty_totals(scores: Sequence[CaseQualityScore]) -> dict[str, float]:
    totals = {dimension: 0.0 for dimension in QUALITY_DIMENSIONS}
    for score in scores:
        for dimension, penalty in score.dimension_penalties.items():
            totals[dimension] = totals.get(dimension, 0.0) + penalty
    return {
        dimension: round(penalty, 4)
        for dimension, penalty in totals.items()
        if penalty > 0
    }


def _split_case_and_response(
    row_or_case: Mapping[str, Any],
    response: Mapping[str, Any] | None,
) -> tuple[Mapping[str, Any], Mapping[str, Any] | None]:
    if response is not None:
        return row_or_case, response
    row = row_or_case
    case = _mapping(row.get("case")) or _mapping(row.get("benchmark_case"))
    actual_response = (
        _mapping(row.get("response"))
        or _mapping(row.get("actual_response"))
        or _mapping(row.get("actual"))
        or _mapping(row.get("backend_response"))
        or _mapping(row.get("response_body"))
        or _mapping(row.get("body"))
        or _mapping(row.get("result"))
    )
    if case:
        return case, actual_response
    if actual_response is not None:
        return row, actual_response
    if _looks_like_response(row):
        return row, row
    return row, None


def _expected(case: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(case.get("expected")) or {}


def _expected_kind(expected: Mapping[str, Any], case: Mapping[str, Any]) -> str | None:
    value = _first_text(
        expected.get("response_kind"),
        expected.get("kind"),
        expected.get("expected_kind"),
        case.get("expected_response_kind"),
        case.get("expected_kind"),
        case.get("response_kind"),
    )
    if value in _UI_EVENT_TO_KIND:
        return _UI_EVENT_TO_KIND[value]
    return value or None


def _actual_response_kind(response: Mapping[str, Any] | None) -> ResponseKind:
    if response is None:
        return "unknown"
    explicit = _first_text(response.get("response_kind"))
    if explicit in {"recommendation_card", "help_card_draft", "clarification", "chitchat"}:
        return explicit  # type: ignore[return-value]

    data = _mapping(response.get("data"))
    if _mapping(data.get("recommendation_card")):
        return "recommendation_card"
    if _mapping(data.get("help_card")):
        return "help_card_draft"
    if _mapping(data.get("clarification")):
        return "clarification"

    for event in _sequence(response.get("ui_events")):
        event_type = _first_text(_mapping(event).get("type"))
        if event_type in _UI_EVENT_TO_KIND:
            return _UI_EVENT_TO_KIND[event_type]  # type: ignore[return-value]
    return "unknown"


def _actual_location_state(response: Mapping[str, Any]) -> str | None:
    value = _first_text(response.get("location_state"))
    if value:
        return value
    card = _recommendation_card(response)
    if card is not None:
        value = _first_text(card.get("location_state"))
        if value:
            return value
    help_card = _help_card(response)
    if help_card is not None:
        value = _first_text(help_card.get("location_state"))
        if value:
            return value
    return None


def _recommendation_card(response: Mapping[str, Any]) -> Mapping[str, Any] | None:
    data = _mapping(response.get("data"))
    return _mapping(data.get("recommendation_card")) or _first_mapping(response.get("cards"))


def _help_card(response: Mapping[str, Any]) -> Mapping[str, Any] | None:
    data = _mapping(response.get("data"))
    return _mapping(data.get("help_card")) or _first_mapping(response.get("help_cards"))


def _expected_tool(
    expected: Mapping[str, Any],
    actual_kind: ResponseKind,
    expected_kind: str | None,
) -> str | None:
    explicit = _first_text(expected.get("tool_call"), expected.get("tool_name"))
    if explicit:
        return explicit
    if (
        expected_kind == "recommendation_card"
        and actual_kind == "help_card_draft"
        and (
            expected.get("allow_help_card_fallback")
            or expected.get("allow_degraded_help_card")
        )
    ):
        return _EXPECTED_TOOL_BY_KIND[actual_kind]
    return _EXPECTED_TOOL_BY_KIND.get(expected_kind or actual_kind)


def _requires_retrieval(
    expected: Mapping[str, Any],
    actual_kind: ResponseKind,
    expected_kind: str | None,
) -> bool:
    value = expected.get("requires_retrieval")
    if value is not None:
        return bool(value)
    return (expected_kind or actual_kind) in {"recommendation_card", "help_card_draft"}


def _requires_agent_run(
    expected: Mapping[str, Any],
    actual_kind: ResponseKind,
    expected_kind: str | None,
) -> bool:
    value = expected.get("requires_agent_run")
    if value is not None:
        return bool(value)
    return (expected_kind or actual_kind) in {"recommendation_card", "help_card_draft"}


def _tool_names(response: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()
    for call in _sequence(response.get("tool_calls")):
        call_map = _mapping(call)
        name = _first_text(call_map.get("name"), call_map.get("tool_name"))
        if name:
            names.add(name)
    for container_key in ("debug", "metadata"):
        container = _mapping(response.get(container_key))
        selected_tool = _first_text(container.get("selected_tool"))
        if selected_tool:
            names.add(selected_tool)
    return names


def _has_retrieval_run(response: Mapping[str, Any]) -> bool:
    metadata = _mapping(response.get("metadata"))
    debug = _mapping(response.get("debug"))
    retrieval_run = metadata.get("retrieval_run")
    return bool(
        metadata.get("retrieval_run_id")
        or _mapping(retrieval_run).get("id")
        or debug.get("retrieval_run_id")
    )


def _has_agent_run(response: Mapping[str, Any]) -> bool:
    metadata = _mapping(response.get("metadata"))
    debug = _mapping(response.get("debug"))
    return bool(metadata.get("agent_run_id") or debug.get("agent_run_id"))


def _trace_id(response: Mapping[str, Any] | None) -> str:
    if response is None:
        return ""
    metadata = _mapping(response.get("metadata"))
    debug = _mapping(response.get("debug"))
    return _first_text(
        metadata.get("trace_id"),
        metadata.get("agent_run_id"),
        response.get("trace_id"),
        response.get("agent_run_id"),
        debug.get("trace_id"),
        debug.get("agent_run_id"),
    )


def _agent_run_id(response: Mapping[str, Any] | None) -> str:
    if response is None:
        return ""
    metadata = _mapping(response.get("metadata"))
    debug = _mapping(response.get("debug"))
    return _first_text(
        metadata.get("agent_run_id"),
        response.get("agent_run_id"),
        debug.get("agent_run_id"),
    )


def _retrieval_run_id(response: Mapping[str, Any] | None) -> str:
    if response is None:
        return ""
    metadata = _mapping(response.get("metadata"))
    debug = _mapping(response.get("debug"))
    retrieval_run = _mapping(metadata.get("retrieval_run"))
    return _first_text(
        metadata.get("retrieval_run_id"),
        retrieval_run.get("id"),
        response.get("retrieval_run_id"),
        debug.get("retrieval_run_id"),
    )


def _has_trusted_image_or_place(card: Mapping[str, Any]) -> bool:
    image = _mapping(card.get("image"))
    if image:
        verified = bool(
            image.get("verified")
            or image.get("is_verified")
            or image.get("verification_status") == "verified"
        )
        return bool(
            verified
            and image.get("displayable") is True
            and image.get("is_ai_generated") is False
            and image.get("source_url")
            and image.get("source_domain")
        )
    place = _mapping(card.get("place"))
    action = _mapping(card.get("action"))
    return bool(place.get("provider") == "amap" and action.get("type") == "open_amap")


def _has_recommendation_evidence(card: Mapping[str, Any]) -> bool:
    if _non_empty_value(card.get("evidence")) or _non_empty_value(card.get("evidence_ids")):
        return True
    provenance = _mapping(card.get("provenance"))
    return bool(
        provenance.get("retrieval_run_id")
        or provenance.get("intent_answer_id")
        or provenance.get("source") in {"eval_seed", "curated_seed", "amap"}
    )


def _looks_like_response(value: Mapping[str, Any]) -> bool:
    return any(
        key in value
        for key in (
            "response_kind",
            "ui_events",
            "data",
            "cards",
            "help_cards",
            "assistant_message",
        )
    )


def _case_id(case: Mapping[str, Any], row: Mapping[str, Any]) -> str:
    return (
        _first_text(
            case.get("id"),
            case.get("case_id"),
            row.get("case_id"),
            row.get("id"),
        )
        or "unknown_case"
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dumped
    return {}


def _sequence(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _first_mapping(value: Any) -> Mapping[str, Any] | None:
    for item in _sequence(value):
        mapped = _mapping(item)
        if mapped:
            return mapped
    return None


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _first_number(*values: Any) -> float | int | None:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return value
    return None


def _non_empty_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return bool(value)
    if isinstance(value, Sequence):
        return bool(value)
    return True
