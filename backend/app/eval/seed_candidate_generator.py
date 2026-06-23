"""Generate seed candidates from attributed benchmark seed gaps."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.services.query_rewrite import rewrite_query


def generate_seed_candidates(
    rows: Sequence[Mapping[str, Any]],
    attributions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows_by_id = {str(row.get("case_id") or ""): row for row in rows}
    grouped: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for attribution in attributions:
        if str(attribution.get("primary_cause")) != "seed_gap":
            continue
        case_id = str(attribution.get("case_id") or "")
        row = rows_by_id.get(case_id, {})
        slots = _extract_slots(row)
        key = (
            str(slots.get("intent_key") or ""),
            str(slots.get("location_state") or "unknown"),
            str(slots.get("target_type") or "restaurant"),
            str(slots.get("domain") or "food"),
        )
        grouped[key].append({**dict(attribution), "_row": row, "_slots": slots})

    candidates: list[dict[str, Any]] = []
    for index, ((intent_key, location_state, target_type, domain), items) in enumerate(
        sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
    ):
        example_ids = [str(item.get("case_id")) for item in items[:10]]
        source_cases = [_source_case_payload(item) for item in items[:25]]
        slots = _merge_slots([_mapping(item.get("_slots")) for item in items])
        priority_score = _priority_score(items)
        all_issues = Counter(
            str(issue)
            for item in items
            for issue in _sequence(item.get("issues"))
        )
        candidates.append(
            {
                "candidate_id": f"seed_candidate_{index:03d}",
                "domain": domain,
                "intent_key": intent_key,
                "location_state": location_state,
                "target_type": target_type,
                "slots": slots,
                "need": "approved_answer",
                "priority": _priority(priority_score),
                "priority_score": priority_score,
                "case_count": len(items),
                "example_case_ids": example_ids,
                "source_cases": source_cases,
                "top_issues": [
                    {"code": code, "count": count}
                    for code, count in all_issues.most_common(10)
                ],
                "suggested_seed": {
                    "answer_type": _answer_type(target_type),
                    "intent_text": _intent_text(slots),
                    "answer_title": _answer_title(slots, target_type),
                    "constraints": {
                        key: value
                        for key, value in slots.items()
                        if key
                        in {
                            "city",
                            "area",
                            "venue",
                            "cuisine",
                            "food_item",
                            "party_size",
                            "spice_preference",
                            "taste_preference",
                            "budget_preference",
                            "user_profile",
                        }
                        and value not in (None, "", [], {})
                    },
                    "decision_factor_count": 1,
                    "requires_evidence": True,
                    "notes": "补 approved answer 后重新跑 product benchmark 验证。",
                },
            }
        )
    return candidates


def write_seed_candidate_reports(
    rows: Sequence[Mapping[str, Any]],
    attributions: Sequence[Mapping[str, Any]],
    output_dir: str | Path,
) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    candidates = generate_seed_candidates(rows, attributions)
    paths = {
        "seed_candidates_jsonl": output / "seed_candidates.jsonl",
        "seed_candidates_json": output / "seed_candidates.json",
        "seed_candidates_markdown": output / "seed_candidates.md",
    }
    paths["seed_candidates_jsonl"].write_text(
        "".join(json.dumps(candidate, ensure_ascii=False, sort_keys=True) + "\n" for candidate in candidates),
        encoding="utf-8",
    )
    paths["seed_candidates_json"].write_text(
        json.dumps({"total": len(candidates), "items": candidates}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    paths["seed_candidates_markdown"].write_text(render_seed_candidates_markdown(candidates), encoding="utf-8")
    return paths


def render_seed_candidates_markdown(candidates: Sequence[Mapping[str, Any]]) -> str:
    lines = ["# Seed Candidates", ""]
    if not candidates:
        lines.append("No seed candidates.")
        return "\n".join(lines) + "\n"
    lines += [
        "| Candidate | Priority | Intent | Slots | Target | Cases | Examples |",
        "| --- | --- | --- | --- | --- | ---: | --- |",
    ]
    for candidate in candidates:
        slots = _mapping(candidate.get("slots"))
        slot_text = ", ".join(
            f"{key}={value}" for key, value in slots.items() if value not in (None, "", [], {})
        )
        lines.append(
            f"| `{candidate.get('candidate_id')}` | `{candidate.get('priority')}` | "
            f"`{candidate.get('intent_key')}` | {slot_text or '-'} | `{candidate.get('target_type')}` | "
            f"{int(candidate.get('case_count') or 0)} | "
            f"{', '.join(f'`{case_id}`' for case_id in _sequence(candidate.get('example_case_ids'))[:5])} |"
        )
    return "\n".join(lines) + "\n"


def _extract_slots(row: Mapping[str, Any]) -> dict[str, Any]:
    case = _mapping(row.get("case"))
    expected = _mapping(row.get("expected")) or _mapping(case.get("expected"))
    message = str(row.get("message") or row.get("input") or case.get("message") or case.get("input") or "")
    rewrite = rewrite_query(message)
    rewrite_slots = dict(rewrite.extracted_slots)
    location_state = str(expected.get("location_state") or row.get("location_state") or "unknown")
    target_type = str(expected.get("target_type") or "restaurant")
    domain = _domain(case)
    rewrite_slots.update(
        {
            "domain": domain,
            "location_state": location_state,
            "target_type": target_type,
        }
    )
    area = rewrite_slots.get("area")
    venue = rewrite_slots.get("venue")
    cuisine = rewrite_slots.get("cuisine")
    food_item = rewrite_slots.get("food_item")
    task = rewrite_slots.get("task")
    rewrite_slots["intent_key"] = ".".join(
        _slug(part)
        for part in (
            domain,
            location_state,
            target_type,
            venue or area or rewrite_slots.get("city") or "unknown_place",
            cuisine or food_item or task or "decision",
        )
        if part
    )
    rewrite_slots["canonical_query"] = rewrite.canonical_query
    return rewrite_slots


def _source_case_payload(item: Mapping[str, Any]) -> dict[str, Any]:
    row = _mapping(item.get("_row"))
    case = _mapping(row.get("case"))
    response = _mapping(row.get("response"))
    actual = _mapping(row.get("actual"))
    trace = _mapping(row.get("trace"))
    response_metadata = _mapping(response.get("metadata"))
    return {
        "case_id": str(item.get("case_id") or row.get("case_id") or case.get("id") or ""),
        "group": str(item.get("group") or row.get("group") or row.get("category") or case.get("category") or "unknown"),
        "message": str(item.get("message") or row.get("message") or row.get("input") or case.get("message") or ""),
        "expected": _mapping(case.get("expected") or row.get("expected")),
        "actual": {
            "response_kind": actual.get("response_kind") or response.get("response_kind"),
            "location_state": actual.get("location_state") or response.get("location_state"),
            "target_type": actual.get("target_type") or _target_type(response),
        },
        "issues": _sequence(item.get("issues")),
        "trace": {
            "trace_id": trace.get("trace_id") or response_metadata.get("trace_id"),
            "agent_run_id": trace.get("agent_run_id") or response_metadata.get("agent_run_id"),
            "retrieval_run_id": trace.get("retrieval_run_id") or response_metadata.get("retrieval_run_id"),
            "runtime_path": trace.get("runtime_path") or response_metadata.get("runtime_path"),
        },
    }


def _target_type(response: Mapping[str, Any]) -> Any:
    data = _mapping(response.get("data"))
    card = _mapping(data.get("recommendation_card"))
    if card:
        return card.get("target_type")
    return response.get("target_type")


def _merge_slots(slots_list: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    keys = [
        "domain",
        "city",
        "area",
        "venue",
        "cuisine",
        "food_item",
        "task",
        "party_size",
        "spice_preference",
        "taste_preference",
        "budget_preference",
        "user_profile",
        "location_state",
        "target_type",
        "canonical_query",
    ]
    merged: dict[str, Any] = {}
    for key in keys:
        values = [slot.get(key) for slot in slots_list if slot.get(key) not in (None, "", [], {})]
        if not values:
            continue
        if isinstance(values[0], list):
            merged[key] = sorted({str(item) for value in values for item in _sequence(value)})
        else:
            merged[key] = Counter(str(value) for value in values).most_common(1)[0][0]
    return merged


def _priority_score(items: Sequence[Mapping[str, Any]]) -> float:
    case_count = len(items)
    quality_penalty = 0.0
    for item in items:
        quality = _mapping(item.get("quality"))
        overall = quality.get("overall")
        try:
            quality_penalty += 1.0 - float(overall)
        except (TypeError, ValueError):
            quality_penalty += 0.5
    return round(case_count * 10 + quality_penalty * 10, 2)


def _intent_text(slots: Mapping[str, Any]) -> str:
    parts = [
        slots.get("city"),
        slots.get("area"),
        slots.get("venue"),
        slots.get("cuisine") or slots.get("food_item"),
        slots.get("task"),
    ]
    return " · ".join(str(part) for part in parts if part)


def _answer_title(slots: Mapping[str, Any], target_type: str) -> str:
    if target_type == "ordering_bundle":
        venue = str(slots.get("venue") or "这家店")
        return f"{venue}点单包"
    area = str(slots.get("area") or slots.get("city") or "这个区域")
    food = str(slots.get("cuisine") or slots.get("food_item") or "餐厅")
    return f"{area}{food}首选"


def _slug(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    replacements = {
        " ": "_",
        "·": "_",
        "/": "_",
        ".": "_",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.lower()


def _domain(case: Mapping[str, Any]) -> str:
    category = str(case.get("category") or case.get("group") or "")
    if "shopping" in category:
        return "shopping"
    if "product" in category:
        return "product"
    if "travel" in category:
        return "travel"
    return "food"


def _priority(score: float) -> str:
    if score >= 100:
        return "P0"
    if score >= 30:
        return "P1"
    return "P2"


def _answer_type(target_type: str) -> str:
    return "ordering_bundle_answer" if target_type == "ordering_bundle" else "area_intent_answer"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []
