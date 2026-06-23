from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.runtime_latency import render_runtime_latency_markdown, summarize_runtime_latency


def test_runtime_latency_summary_groups_tools_and_counts_slow_failures() -> None:
    base = datetime(2026, 6, 24, 10, tzinfo=timezone.utc)

    summary = summarize_runtime_latency(
        agent_runs=[
            _row("agent-1", "pipi_chat", "succeeded", base, 500),
            _row("agent-2", "pipi_chat", "failed", base, 2200),
        ],
        tool_calls=[
            _row("tool-1", "search_knowledge", "succeeded", base, 120),
            _row("tool-2", "create_recommendation_card", "succeeded", base, 400),
            _row("tool-3", "search_knowledge", "failed", base, 1100),
        ],
        retrieval_runs=[
            _row("retrieval-1", "deterministic_db", "succeeded", base, 80),
            _row("retrieval-2", "deterministic_db", "succeeded", base, 900),
        ],
        window={"hours": 24},
    )

    assert summary["agent_runs"]["count"] == 2
    assert summary["agent_runs"]["p50_ms"] == 1350.0
    assert summary["agent_runs"]["slow_count"] == 1
    assert summary["agent_runs"]["failure_count"] == 1
    assert summary["tool_calls"]["count"] == 3
    assert summary["tool_calls"]["p95_ms"] == 1030.0
    assert summary["tool_calls"]["slow_count"] == 1
    assert summary["tool_calls"]["failure_count"] == 1
    assert summary["tool_calls"]["by_group"]["search_knowledge"]["count"] == 2
    assert summary["retrieval_runs"]["slow_count"] == 1
    assert summary["slowest"]["tool_calls"][0]["id"] == "tool-3"
    assert summary["cost"]["tracking_status"] == "not_available_until_llm_provider_costs"


def test_runtime_latency_markdown_renders_sections() -> None:
    summary = summarize_runtime_latency(
        agent_runs=[],
        tool_calls=[],
        retrieval_runs=[],
        window={"hours": 1, "since": "2026-06-24T10:00:00+00:00"},
    )

    markdown = render_runtime_latency_markdown(summary)

    assert "# Pipi Runtime Latency Summary" in markdown
    assert "## Agent Runs" in markdown
    assert "## Tool Calls" in markdown
    assert "## Retrieval Runs" in markdown
    assert "not_available_until_llm_provider_costs" in markdown


def _row(
    id: str,
    label: str,
    status: str,
    started_at: datetime,
    duration_ms: int,
) -> dict[str, object]:
    return {
        "id": id,
        "run_type": label,
        "tool_name": label,
        "source": label,
        "status": status,
        "started_at": started_at,
        "finished_at": started_at + timedelta(milliseconds=duration_ms),
    }

