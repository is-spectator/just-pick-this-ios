"""Generate seed candidates from attributed benchmark seed gaps."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


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
        grouped[key].append(attribution)

    candidates: list[dict[str, Any]] = []
    for index, ((intent_key, location_state, target_type, domain), items) in enumerate(
        sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
    ):
        example_ids = [str(item.get("case_id")) for item in items[:10]]
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
                "need": "approved_answer",
                "priority": _priority(len(items)),
                "case_count": len(items),
                "example_case_ids": example_ids,
                "top_issues": [
                    {"code": code, "count": count}
                    for code, count in all_issues.most_common(10)
                ],
                "suggested_seed": {
                    "answer_type": _answer_type(target_type),
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
    lines += ["| Candidate | Priority | Intent | Target | Cases | Examples |", "| --- | --- | --- | --- | ---: | --- |"]
    for candidate in candidates:
        lines.append(
            f"| `{candidate.get('candidate_id')}` | `{candidate.get('priority')}` | "
            f"`{candidate.get('intent_key')}` | `{candidate.get('target_type')}` | "
            f"{int(candidate.get('case_count') or 0)} | "
            f"{', '.join(f'`{case_id}`' for case_id in _sequence(candidate.get('example_case_ids'))[:5])} |"
        )
    return "\n".join(lines) + "\n"


def _extract_slots(row: Mapping[str, Any]) -> dict[str, Any]:
    case = _mapping(row.get("case"))
    expected = _mapping(row.get("expected")) or _mapping(case.get("expected"))
    message = str(row.get("message") or row.get("input") or case.get("message") or case.get("input") or "")
    location_state = str(expected.get("location_state") or row.get("location_state") or "unknown")
    target_type = str(expected.get("target_type") or "restaurant")
    area = _first_known(message, ["三里屯", "朝阳区", "望京", "南锣鼓巷", "前门", "故宫", "大同"])
    venue = _first_known(message, ["海底捞", "四季民福", "喜晋道"])
    cuisine = _first_known(message, ["川菜", "火锅", "烤鸭", "粤菜", "贵州菜"])
    food_item = _first_known(message, ["热干面", "刀削面", "烤肉"])
    return {
        "domain": _domain(case),
        "area": area,
        "venue": venue,
        "cuisine": cuisine,
        "food_item": food_item,
        "location_state": location_state,
        "target_type": target_type,
        "intent_key": ".".join(
            part
            for part in (
                _domain(case),
                location_state,
                target_type,
                venue or area or "unknown_place",
                cuisine or food_item or "food",
            )
            if part
        ),
    }


def _domain(case: Mapping[str, Any]) -> str:
    category = str(case.get("category") or case.get("group") or "")
    if "shopping" in category:
        return "shopping"
    if "product" in category:
        return "product"
    if "travel" in category:
        return "travel"
    return "food"


def _priority(count: int) -> str:
    if count >= 10:
        return "P0"
    if count >= 3:
        return "P1"
    return "P2"


def _answer_type(target_type: str) -> str:
    return "ordering_bundle_answer" if target_type == "ordering_bundle" else "area_intent_answer"


def _first_known(text: str, values: Sequence[str]) -> str | None:
    return next((value for value in values if value in text), None)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []
