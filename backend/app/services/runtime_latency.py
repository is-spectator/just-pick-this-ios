from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AgentRun, RetrievalRun, ToolCall
from app.services.runtime import utcnow


DEFAULT_AGENT_SLOW_THRESHOLD_MS = 1500.0
DEFAULT_TOOL_SLOW_THRESHOLD_MS = 800.0
DEFAULT_RETRIEVAL_SLOW_THRESHOLD_MS = 800.0


def runtime_latency_summary(
    session: Session,
    *,
    hours: int = 24,
    limit: int = 500,
) -> dict[str, Any]:
    resolved_hours = max(1, min(int(hours or 24), 24 * 30))
    resolved_limit = max(1, min(int(limit or 500), 5000))
    since = utcnow() - timedelta(hours=resolved_hours)

    agent_runs = list(
        session.scalars(
            select(AgentRun)
            .where(AgentRun.created_at >= since)
            .order_by(AgentRun.created_at.desc())
            .limit(resolved_limit)
        )
    )
    tool_calls = list(
        session.scalars(
            select(ToolCall)
            .where(ToolCall.created_at >= since)
            .order_by(ToolCall.created_at.desc())
            .limit(resolved_limit)
        )
    )
    retrieval_runs = list(
        session.scalars(
            select(RetrievalRun)
            .where(RetrievalRun.created_at >= since)
            .order_by(RetrievalRun.created_at.desc())
            .limit(resolved_limit)
        )
    )
    return summarize_runtime_latency(
        agent_runs=[_agent_run_record(row) for row in agent_runs],
        tool_calls=[_tool_call_record(row) for row in tool_calls],
        retrieval_runs=[_retrieval_run_record(row) for row in retrieval_runs],
        window={"hours": resolved_hours, "since": since.isoformat(), "limit": resolved_limit},
    )


def summarize_runtime_latency(
    *,
    agent_runs: Sequence[Mapping[str, Any]],
    tool_calls: Sequence[Mapping[str, Any]],
    retrieval_runs: Sequence[Mapping[str, Any]],
    window: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    agent_summary = _summarize_group(
        agent_runs,
        group_key="run_type",
        slow_threshold_ms=DEFAULT_AGENT_SLOW_THRESHOLD_MS,
    )
    tool_summary = _summarize_group(
        tool_calls,
        group_key="tool_name",
        slow_threshold_ms=DEFAULT_TOOL_SLOW_THRESHOLD_MS,
    )
    retrieval_summary = _summarize_group(
        retrieval_runs,
        group_key="source",
        slow_threshold_ms=DEFAULT_RETRIEVAL_SLOW_THRESHOLD_MS,
    )
    return {
        "window": dict(window or {}),
        "agent_runs": agent_summary,
        "tool_calls": tool_summary,
        "retrieval_runs": retrieval_summary,
        "slowest": {
            "agent_runs": _slowest(agent_runs, label_key="run_type"),
            "tool_calls": _slowest(tool_calls, label_key="tool_name"),
            "retrieval_runs": _slowest(retrieval_runs, label_key="source"),
        },
        "latency_budget": _latency_budget_summary(
            agent_summary=agent_summary,
            tool_summary=tool_summary,
            retrieval_summary=retrieval_summary,
        ),
        "cost": {
            "estimated_cost_usd": None,
            "tracking_status": "not_available_until_llm_provider_costs",
            "note": "Current product path is deterministic; token/provider cost tracking starts when product LLM mode is promoted.",
        },
        "metadata": {
            "version": "runtime_latency_v1",
            "slow_thresholds_ms": {
                "agent_run": DEFAULT_AGENT_SLOW_THRESHOLD_MS,
                "tool_call": DEFAULT_TOOL_SLOW_THRESHOLD_MS,
                "retrieval_run": DEFAULT_RETRIEVAL_SLOW_THRESHOLD_MS,
            },
        },
    }


def render_runtime_latency_markdown(summary: Mapping[str, Any]) -> str:
    lines = ["# Pipi Runtime Latency Summary", ""]
    window = _mapping(summary.get("window"))
    if window:
        lines.append(
            f"- Window: `{window.get('hours', '-')}`h since `{window.get('since', '-')}`"
        )
        lines.append("")
    for key, title in (
        ("agent_runs", "Agent Runs"),
        ("tool_calls", "Tool Calls"),
        ("retrieval_runs", "Retrieval Runs"),
    ):
        section = _mapping(summary.get(key))
        lines += [
            f"## {title}",
            "",
            f"- Count: `{section.get('count', 0)}`",
            f"- P50: `{section.get('p50_ms')}` ms",
            f"- P95: `{section.get('p95_ms')}` ms",
            f"- Slow: `{section.get('slow_count', 0)}`",
            "",
        ]
        by_group = _mapping(section.get("by_group"))
        if by_group:
            lines += ["| Group | Count | P50 ms | P95 ms | Slow | Failures |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
            for group, group_summary in sorted(by_group.items()):
                item = _mapping(group_summary)
                lines.append(
                    f"| `{group}` | {item.get('count', 0)} | {item.get('p50_ms')} | "
                    f"{item.get('p95_ms')} | {item.get('slow_count', 0)} | {item.get('failure_count', 0)} |"
                )
            lines.append("")
    cost = _mapping(summary.get("cost"))
    budget = _mapping(summary.get("latency_budget"))
    lines += [
        "## Latency Budget",
        "",
        f"- Overall target met: `{budget.get('overall_target_met')}`",
        f"- Agent P95 target: `{budget.get('agent_p95_target_ms')}` ms",
        f"- Agent P95 actual: `{budget.get('agent_p95_ms')}` ms",
        "",
    ]
    lines += [
        "## Cost",
        "",
        f"- Tracking: `{cost.get('tracking_status', 'unknown')}`",
        f"- Estimated cost: `{cost.get('estimated_cost_usd')}`",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _latency_budget_summary(
    *,
    agent_summary: Mapping[str, Any],
    tool_summary: Mapping[str, Any],
    retrieval_summary: Mapping[str, Any],
) -> dict[str, Any]:
    agent_met = _p95_target_met(agent_summary, DEFAULT_AGENT_SLOW_THRESHOLD_MS)
    tool_met = _p95_target_met(tool_summary, DEFAULT_TOOL_SLOW_THRESHOLD_MS)
    retrieval_met = _p95_target_met(retrieval_summary, DEFAULT_RETRIEVAL_SLOW_THRESHOLD_MS)
    evaluated = [value for value in (agent_met, tool_met, retrieval_met) if value is not None]
    return {
        "version": "latency_budget_v1",
        "agent_p95_target_ms": DEFAULT_AGENT_SLOW_THRESHOLD_MS,
        "tool_p95_target_ms": DEFAULT_TOOL_SLOW_THRESHOLD_MS,
        "retrieval_p95_target_ms": DEFAULT_RETRIEVAL_SLOW_THRESHOLD_MS,
        "agent_p95_ms": agent_summary.get("p95_ms"),
        "tool_p95_ms": tool_summary.get("p95_ms"),
        "retrieval_p95_ms": retrieval_summary.get("p95_ms"),
        "agent_p95_target_met": agent_met,
        "tool_p95_target_met": tool_met,
        "retrieval_p95_target_met": retrieval_met,
        "overall_target_met": all(evaluated) if evaluated else None,
        "slow_total": int(agent_summary.get("slow_count") or 0)
        + int(tool_summary.get("slow_count") or 0)
        + int(retrieval_summary.get("slow_count") or 0),
        "failure_total": int(agent_summary.get("failure_count") or 0)
        + int(tool_summary.get("failure_count") or 0)
        + int(retrieval_summary.get("failure_count") or 0),
    }


def _p95_target_met(summary: Mapping[str, Any], target_ms: float) -> bool | None:
    p95 = summary.get("p95_ms")
    if p95 is None:
        return None
    try:
        return float(p95) <= target_ms
    except (TypeError, ValueError):
        return None


def _summarize_group(
    rows: Sequence[Mapping[str, Any]],
    *,
    group_key: str,
    slow_threshold_ms: float,
    include_groups: bool = True,
) -> dict[str, Any]:
    durations = [_duration_ms(row) for row in rows]
    valid_durations = [value for value in durations if value is not None]
    failures = [row for row in rows if str(row.get("status") or "").lower() in {"failed", "error", "timeout"}]
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(group_key) or "unknown")].append(row)
    return {
        "count": len(rows),
        "duration_count": len(valid_durations),
        "p50_ms": _percentile(valid_durations, 50),
        "p95_ms": _percentile(valid_durations, 95),
        "max_ms": round(max(valid_durations), 3) if valid_durations else None,
        "slow_threshold_ms": slow_threshold_ms,
        "slow_count": sum(1 for value in valid_durations if value > slow_threshold_ms),
        "failure_count": len(failures),
        "status_counts": dict(Counter(str(row.get("status") or "unknown") for row in rows)),
        "by_group": {
            group: _summarize_group(
                group_rows,
                group_key=group_key,
                slow_threshold_ms=slow_threshold_ms,
                include_groups=False,
            )
            for group, group_rows in groups.items()
        }
        if include_groups and (len(groups) > 1 or (groups and next(iter(groups)) != "unknown"))
        else {},
    }


def _slowest(rows: Sequence[Mapping[str, Any]], *, label_key: str, limit: int = 10) -> list[dict[str, Any]]:
    sortable = [
        (duration, row)
        for row in rows
        if (duration := _duration_ms(row)) is not None
    ]
    sortable.sort(key=lambda item: item[0], reverse=True)
    items: list[dict[str, Any]] = []
    for duration, row in sortable[:limit]:
        items.append(
            {
                "id": str(row.get("id") or ""),
                "label": str(row.get(label_key) or "unknown"),
                "status": str(row.get("status") or "unknown"),
                "duration_ms": round(duration, 3),
                "started_at": _iso(row.get("started_at")),
                "finished_at": _iso(row.get("finished_at")),
            }
        )
    return items


def _duration_ms(row: Mapping[str, Any]) -> float | None:
    explicit = row.get("duration_ms")
    if explicit is not None:
        try:
            return float(explicit)
        except (TypeError, ValueError):
            return None
    started_at = _datetime(row.get("started_at"))
    finished_at = _datetime(row.get("finished_at"))
    if started_at is None or finished_at is None:
        return None
    return max(0.0, (finished_at - started_at).total_seconds() * 1000)


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    sorted_values = sorted(float(value) for value in values)
    if len(sorted_values) == 1:
        return round(sorted_values[0], 3)
    rank = (len(sorted_values) - 1) * (percentile / 100)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = rank - lower
    value = sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight
    return round(value, 3)


def _agent_run_record(row: AgentRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_type": row.run_type,
        "status": row.status,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
    }


def _tool_call_record(row: ToolCall) -> dict[str, Any]:
    return {
        "id": row.id,
        "tool_name": row.tool_name,
        "status": row.status,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
    }


def _retrieval_run_record(row: RetrievalRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "source": row.source,
        "status": row.status,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
    }


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _iso(value: Any) -> str | None:
    dt = _datetime(value)
    return dt.isoformat() if dt is not None else None


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}
