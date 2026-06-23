"""Generate structured agent-fix issues from quality attributions."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


AGENT_CAUSES = {"agent_bug", "card_quality", "retrieval_gap", "latency"}


def generate_agent_fix_issues(attributions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for attribution in attributions:
        cause = str(attribution.get("primary_cause") or "unknown")
        if cause not in AGENT_CAUSES:
            continue
        issue_key = _main_issue(attribution)
        grouped[(cause, issue_key)].append(attribution)

    issues: list[dict[str, Any]] = []
    for index, ((cause, issue_key), items) in enumerate(
        sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
    ):
        case_ids = [str(item.get("case_id")) for item in items[:20]]
        group_counts = Counter(str(item.get("group") or "unknown") for item in items)
        issues.append(
            {
                "issue_id": f"agent_fix_{index:03d}",
                "primary_cause": cause,
                "issue_key": issue_key,
                "priority": _priority(cause, len(items)),
                "owner": _owner(cause, issue_key),
                "case_count": len(items),
                "case_ids": case_ids,
                "groups": dict(sorted(group_counts.items())),
                "title": _title(cause, issue_key),
                "suggested_scope": _suggested_scope(cause, issue_key),
                "acceptance": [
                    "对应 case 不再出现在 low-quality / agent fix 队列中。",
                    "product path 仍为 runtime_path=product。",
                    "新增或更新回归测试覆盖该 issue_key。",
                ],
            }
        )
    return issues


def write_agent_fix_issue_reports(
    attributions: Sequence[Mapping[str, Any]],
    output_dir: str | Path,
) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    issues = generate_agent_fix_issues(attributions)
    paths = {
        "agent_fix_issues_json": output / "agent_fix_issues.json",
        "agent_fix_issues_markdown": output / "agent_fix_issues.md",
        "agent_fix_issues_jsonl": output / "agent_fix_issues.jsonl",
    }
    paths["agent_fix_issues_json"].write_text(
        json.dumps({"total": len(issues), "items": issues}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    paths["agent_fix_issues_jsonl"].write_text(
        "".join(json.dumps(issue, ensure_ascii=False, sort_keys=True) + "\n" for issue in issues),
        encoding="utf-8",
    )
    paths["agent_fix_issues_markdown"].write_text(render_agent_fix_issues_markdown(issues), encoding="utf-8")
    return paths


def render_agent_fix_issues_markdown(issues: Sequence[Mapping[str, Any]]) -> str:
    lines = ["# Agent Fix Issues", ""]
    if not issues:
        lines.append("No agent fix issues.")
        return "\n".join(lines) + "\n"
    lines += ["| Issue | Priority | Owner | Cause | Cases | Scope |", "| --- | --- | --- | --- | ---: | --- |"]
    for issue in issues:
        lines.append(
            f"| `{issue.get('issue_id')}` | `{issue.get('priority')}` | `{issue.get('owner')}` | "
            f"`{issue.get('primary_cause')}` | {int(issue.get('case_count') or 0)} | "
            f"{_escape(issue.get('suggested_scope') or '')} |"
        )
    lines += ["", "## Details", ""]
    for issue in issues:
        case_ids = ", ".join(f"`{case_id}`" for case_id in _sequence(issue.get("case_ids"))[:10])
        lines += [
            f"### `{issue.get('issue_id')}` {issue.get('title')}",
            "",
            f"- priority: `{issue.get('priority')}`",
            f"- owner: `{issue.get('owner')}`",
            f"- issue_key: `{issue.get('issue_key')}`",
            f"- cases: {case_ids or '-'}",
            "",
        ]
    return "\n".join(lines) + "\n"


def _main_issue(attribution: Mapping[str, Any]) -> str:
    issues = _sequence(attribution.get("issues"))
    return str(issues[0] if issues else "unknown")


def _priority(cause: str, count: int) -> str:
    if cause == "agent_bug":
        return "P0" if count >= 3 else "P1"
    if cause == "retrieval_gap":
        return "P1"
    if cause == "latency":
        return "P1" if count >= 5 else "P2"
    return "P2"


def _owner(cause: str, issue_key: str) -> str:
    if cause == "retrieval_gap":
        return "retrieval"
    if cause == "latency":
        return "runtime"
    if issue_key.startswith("help_card_"):
        return "help_card"
    if issue_key.startswith("recommendation_card_"):
        return "card_contract"
    if "target_type" in issue_key or "location_state" in issue_key or "response_kind" in issue_key:
        return "router"
    return "agent"


def _title(cause: str, issue_key: str) -> str:
    return f"{cause} / {issue_key}"


def _suggested_scope(cause: str, issue_key: str) -> str:
    if cause == "retrieval_gap":
        return "检查 retrieval/provenance/evidence 写入，不要绕过证据闸门。"
    if cause == "latency":
        return "检查 product path 慢点和外部依赖超时。"
    if issue_key.startswith("help_card_"):
        return "收紧 draft/update help card 的结构化槽位和质量 gate。"
    if issue_key.startswith("recommendation_card_"):
        return "修 recommendation card tool/evaluator/serializer 的 v2 contract。"
    return "修 InputGate/query rewrite/reasoner/tool loop 的最小范围。"


def _escape(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _sequence(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []
