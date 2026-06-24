#!/usr/bin/env python3
"""Run local product turns and write evaluated benchmark results."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.eval.reporting import generate_quality_reports_from_files, load_benchmark_cases  # noqa: E402
from app.eval.results_guard import validate_benchmark_results, write_results_guard_report  # noqa: E402
from app.main import create_app  # noqa: E402


@dataclass(frozen=True)
class ProductBenchmarkConfig:
    benchmark_path: Path
    output_dir: Path
    limit: int | None = None
    generate_reports: bool = True
    run_id: str | None = None


async def run_product_benchmark(config: ProductBenchmarkConfig) -> dict[str, Any]:
    cases = load_benchmark_cases(config.benchmark_path)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    run_id = config.run_id or _default_run_id()
    results_path = config.output_dir / "results.jsonl"
    rows: list[dict[str, Any]] = []

    with _product_env():
        get_settings.cache_clear()
        blocker = _database_readiness_blocker()
        if blocker is not None:
            _write_blocked_benchmark_summary(config, run_id=run_id, blocker=blocker)
            raise RuntimeError(str(blocker["message"]))
        app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            timeout=30.0,
        ) as client:
            with results_path.open("w", encoding="utf-8") as output:
                for case in cases:
                    if config.limit is not None and len(rows) >= config.limit:
                        break
                    row = await _run_case(
                        client,
                        case=case,
                        suite_id=_suite_id(config.benchmark_path),
                        run_id=run_id,
                    )
                    rows.append(row)
                    output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                    output.flush()

    get_settings.cache_clear()

    if not rows:
        raise RuntimeError("product benchmark produced zero evaluated rows")

    guard = validate_benchmark_results(results_path, require_latency_ms=True)
    guard_paths = write_results_guard_report(guard, config.output_dir)
    report_paths: dict[str, str] = {key: str(value) for key, value in guard_paths.items()}
    if config.generate_reports:
        generated = generate_quality_reports_from_files(
            results_path=results_path,
            output_dir=config.output_dir,
            benchmark_path=config.benchmark_path,
        )
        report_paths.update({key: str(value) for key, value in generated.items()})

    runtime_gate = _product_runtime_gate(rows)
    summary = {
        "ok": runtime_gate["ok"],
        "run_id": run_id,
        "benchmark": str(config.benchmark_path),
        "output_dir": str(config.output_dir),
        "results_path": str(results_path),
        "evaluated_cases": len(rows),
        "guard": guard,
        "runtime_gate": runtime_gate,
        "benchmark_coverage": _benchmark_coverage_summary(
            benchmark_path=config.benchmark_path,
            rows=rows,
            total_case_count=len(cases),
            limit=config.limit,
        ),
        "stats": _benchmark_stats(rows),
        "report_paths": report_paths,
    }
    (config.output_dir / "product_benchmark_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (config.output_dir / "product_benchmark_summary.md").write_text(
        _render_summary_markdown(summary),
        encoding="utf-8",
    )
    _write_latest_pointer(config.output_dir, summary)
    if not runtime_gate["ok"]:
        raise RuntimeError(
            "product benchmark runtime gate failed: "
            f"{runtime_gate['failed_rows']} failed row(s)"
        )
    return summary


async def _run_case(
    client: AsyncClient,
    *,
    case: Mapping[str, Any],
    suite_id: str,
    run_id: str,
) -> dict[str, Any]:
    case_id = _case_id(case)
    group = _case_group(case)
    message = str(case.get("message") or case.get("input") or "").strip()
    device_uid = f"product-bench-{case_id}-{uuid.uuid4()}"
    started = time.perf_counter()

    bootstrap_response = await client.post(
        "/v1/bootstrap",
        json={
            "device_uid": device_uid,
            "platform": "product-benchmark",
            "app_version": "0.1.0",
            "metadata": {"source": "run_product_benchmark"},
        },
    )
    if bootstrap_response.status_code != 200:
        return _result_row(
            case=case,
            case_id=case_id,
            group=group,
            message=message,
            status_code=bootstrap_response.status_code,
            latency_ms=_elapsed_ms(started),
            response=_safe_response_json(bootstrap_response),
            error="bootstrap_failed",
            run_id=run_id,
        )

    conversation_id = str(bootstrap_response.json().get("conversation_id") or "")
    response = await client.post(
        "/v1/chat/turn",
        json={
            "device_uid": device_uid,
            "conversation_id": conversation_id,
            "message": message,
            "client_context": {
                "source": "run_product_benchmark",
                "benchmark_suite_id": suite_id,
                "benchmark_case_id": case_id,
                "benchmark_group": group,
                "include_debug": False,
                "mode": "product_benchmark",
            },
            "metadata": {
                "benchmark_case_id": case_id,
                "benchmark_group": group,
            },
        },
    )
    body = _safe_response_json(response)
    return _result_row(
        case=case,
        case_id=case_id,
        group=group,
        message=message,
        status_code=response.status_code,
        latency_ms=_elapsed_ms(started),
        response=body,
        actual_summary=_actual_summary(body),
        metadata_loop_tool_calls=_metadata_loop_tool_calls(body),
        run_id=run_id,
    )


def _result_row(
    *,
    case: Mapping[str, Any],
    case_id: str,
    group: str,
    message: str,
    status_code: int,
    latency_ms: float,
    response: Mapping[str, Any],
    actual_summary: Mapping[str, Any] | None = None,
    metadata_loop_tool_calls: Sequence[str] | None = None,
    error: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    metadata = response.get("metadata") if isinstance(response, Mapping) else {}
    metadata = metadata if isinstance(metadata, Mapping) else {}
    actual = dict(actual_summary or _actual_summary(response))
    runtime_path = str(metadata.get("runtime_path") or "unknown")
    trace = _trace_summary(response)
    status = "passed" if status_code == 200 and runtime_path == "product" else "failed"
    issues: list[str] = []
    if status_code != 200:
        issues.append("http_status_not_200")
    if runtime_path != "product":
        issues.append("runtime_bypass")
    row: dict[str, Any] = {
        "run_id": run_id,
        "case_id": case_id,
        "category": group,
        "group": group,
        "input": message,
        "message": message,
        "expected": dict(case.get("expected") or {}),
        "actual": actual,
        "trace": trace,
        "status": status,
        "case": dict(case),
        "status_code": status_code,
        "latency_ms": latency_ms,
        "response": dict(response),
        "actual_summary": actual,
        "agent_run_id": str(metadata.get("agent_run_id") or "") or None,
        "trace_id": str(metadata.get("agent_run_id") or "") or None,
        "retrieval_run_id": _retrieval_run_id(response),
        "metadata_loop_tool_calls": list(metadata_loop_tool_calls or _metadata_loop_tool_calls(response)),
    }
    if issues:
        row["issues"] = issues
    if error:
        row["error"] = error
    return row


def _actual_summary(response: Mapping[str, Any]) -> dict[str, Any]:
    data = response.get("data") if isinstance(response.get("data"), Mapping) else {}
    card = data.get("recommendation_card") if isinstance(data.get("recommendation_card"), Mapping) else {}
    help_card = data.get("help_card") if isinstance(data.get("help_card"), Mapping) else {}
    return {
        "response_kind": response.get("response_kind"),
        "location_state": response.get("location_state"),
        "target_type": card.get("target_type") or help_card.get("target_type") or "none",
    }


def _metadata_loop_tool_calls(response: Mapping[str, Any]) -> list[str]:
    metadata = response.get("metadata") if isinstance(response.get("metadata"), Mapping) else {}
    loop = metadata.get("loop") if isinstance(metadata.get("loop"), Mapping) else {}
    return [str(item) for item in (loop.get("tool_calls") or [])]


def _trace_summary(response: Mapping[str, Any]) -> dict[str, Any]:
    metadata = response.get("metadata") if isinstance(response.get("metadata"), Mapping) else {}
    loop = metadata.get("loop") if isinstance(metadata.get("loop"), Mapping) else {}
    return {
        "trace_id": str(metadata.get("trace_id") or metadata.get("agent_run_id") or "") or None,
        "agent_run_id": str(metadata.get("agent_run_id") or "") or None,
        "retrieval_run_id": _retrieval_run_id(response),
        "runtime_path": str(metadata.get("runtime_path") or "unknown"),
        "loop": dict(loop),
    }


def _retrieval_run_id(response: Mapping[str, Any]) -> str | None:
    metadata = response.get("metadata") if isinstance(response.get("metadata"), Mapping) else {}
    retrieval_run = metadata.get("retrieval_run")
    if isinstance(retrieval_run, Mapping) and retrieval_run.get("id"):
        return str(retrieval_run.get("id"))
    value = metadata.get("retrieval_run_id")
    return str(value) if value else None


def _benchmark_stats(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    latency_values = sorted(
        value
        for value in (_latency_ms(row) for row in rows)
        if value is not None and value >= 0
    )
    status_counts = Counter(str(row.get("status_code") or "unknown") for row in rows)
    response_kind_counts = Counter(
        str(_actual_summary_from_row(row).get("response_kind") or "unknown") for row in rows
    )
    runtime_path_counts = Counter(_runtime_path(row) for row in rows)
    slowest_cases = sorted(
        (
            {
                "case_id": row.get("case_id"),
                "category": row.get("category") or row.get("group"),
                "latency_ms": _latency_ms(row),
                "status_code": row.get("status_code"),
                "response_kind": _actual_summary_from_row(row).get("response_kind"),
                "runtime_path": _runtime_path(row),
            }
            for row in rows
            if _latency_ms(row) is not None
        ),
        key=lambda item: float(item.get("latency_ms") or 0),
        reverse=True,
    )[:10]
    return {
        "latency": {
            "count": len(latency_values),
            "p50_ms": _percentile(latency_values, 50),
            "p95_ms": _percentile(latency_values, 95),
            "max_ms": round(latency_values[-1], 4) if latency_values else None,
        },
        "status_code_counts": dict(sorted(status_counts.items())),
        "response_kind_counts": dict(sorted(response_kind_counts.items())),
        "runtime_path_counts": dict(sorted(runtime_path_counts.items())),
        "slowest_cases": slowest_cases,
    }


def _product_runtime_gate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    for row in rows:
        issues = [str(item) for item in (row.get("issues") or [])]
        if str(row.get("status") or "") == "passed" and not issues:
            continue
        failures.append(
            {
                "case_id": row.get("case_id"),
                "category": row.get("category") or row.get("group"),
                "status": row.get("status"),
                "status_code": row.get("status_code"),
                "runtime_path": _runtime_path(row),
                "issues": issues,
            }
        )
    return {
        "ok": not failures,
        "total_rows": len(rows),
        "failed_rows": len(failures),
        "failure_samples": failures[:20],
    }


def _actual_summary_from_row(row: Mapping[str, Any]) -> Mapping[str, Any]:
    summary = row.get("actual_summary")
    if isinstance(summary, Mapping):
        return summary
    response = row.get("response")
    return _actual_summary(response if isinstance(response, Mapping) else {})


def _runtime_path(row: Mapping[str, Any]) -> str:
    response = row.get("response")
    response = response if isinstance(response, Mapping) else {}
    metadata = response.get("metadata") if isinstance(response.get("metadata"), Mapping) else {}
    return str(metadata.get("runtime_path") or "unknown")


def _latency_ms(row: Mapping[str, Any]) -> float | None:
    value = row.get("latency_ms")
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _percentile(values: Sequence[float], percentile: int) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 4)
    rank = (len(values) - 1) * (percentile / 100)
    lower = int(rank)
    upper = min(lower + 1, len(values) - 1)
    fraction = rank - lower
    observed = values[lower] + (values[upper] - values[lower]) * fraction
    return round(observed, 4)


def _case_id(case: Mapping[str, Any]) -> str:
    return str(case.get("id") or case.get("case_id") or uuid.uuid4()).strip()


def _case_group(case: Mapping[str, Any]) -> str:
    return str(case.get("category") or case.get("group") or "unknown").strip() or "unknown"


def _suite_id(benchmark_path: Path) -> str:
    return benchmark_path.stem


def _default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_latest_pointer(output_dir: Path, summary: Mapping[str, Any]) -> None:
    latest = {
        "ok": summary.get("ok"),
        "run_id": summary.get("run_id"),
        "output_dir": summary.get("output_dir"),
        "results_path": summary.get("results_path"),
        "evaluated_cases": summary.get("evaluated_cases"),
        "runtime_gate": summary.get("runtime_gate"),
        "benchmark_coverage": summary.get("benchmark_coverage"),
        "stats": summary.get("stats"),
    }
    (output_dir.parent / "latest.json").write_text(
        json.dumps(latest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _database_readiness_blocker() -> dict[str, str] | None:
    settings = get_settings()
    if settings.database_url is None:
        return {
            "code": "missing_database_url",
            "message": "DATABASE_URL is not configured; product benchmark requires a database.",
        }

    engine = None
    try:
        engine = create_engine(str(settings.database_url), pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("select 1"))
    except (SQLAlchemyError, OSError) as exc:
        return {
            "code": "database_unreachable",
            "message": (
                "DATABASE_URL is configured but unreachable; start Postgres/Docker "
                "or run ./scripts/test.sh for a managed integration database."
            ),
            "error": exc.__class__.__name__,
        }
    finally:
        if engine is not None:
            engine.dispose()
    return None


def _write_blocked_benchmark_summary(
    config: ProductBenchmarkConfig,
    *,
    run_id: str,
    blocker: Mapping[str, str],
) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    results_path = config.output_dir / "results.jsonl"
    results_path.write_text("", encoding="utf-8")
    summary = {
        "ok": False,
        "status": "blocked",
        "run_id": run_id,
        "benchmark": str(config.benchmark_path),
        "output_dir": str(config.output_dir),
        "results_path": str(results_path),
        "evaluated_cases": 0,
        "blocker": dict(blocker),
        "stats": {
            "latency": {"count": 0, "p50_ms": None, "p95_ms": None, "max_ms": None},
            "status_code_counts": {},
            "response_kind_counts": {},
            "runtime_path_counts": {},
            "slowest_cases": [],
        },
        "benchmark_coverage": {
            "suite_id": _suite_id(config.benchmark_path),
            "target_case_count": None,
            "case_count": 0,
            "evaluated_case_count": 0,
            "is_limited_run": config.limit is not None,
            "coverage_complete": False,
            "runtime_path_required": "product",
            "by_category": {},
            "evaluated_by_category": {},
            "expected_distribution": {},
        },
        "runtime_gate": {
            "ok": False,
            "total_rows": 0,
            "failed_rows": 0,
            "failure_samples": [],
        },
    }
    (config.output_dir / "product_benchmark_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (config.output_dir / "product_benchmark_summary.md").write_text(
        _render_blocked_summary_markdown(summary),
        encoding="utf-8",
    )
    _write_latest_pointer(config.output_dir, summary)


def _safe_response_json(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception:
        return {"raw_text": getattr(response, "text", "")}
    return payload if isinstance(payload, dict) else {"payload": payload}


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


@contextmanager
def _product_env() -> Iterable[None]:
    updates = {
        "APP_ENV": "test",
        "PIPI_EVAL_MODE": "false",
        "ALLOW_EVAL_BYPASS": "false",
        "AUTO_SEED_ON_REQUEST": "false",
        "PIPI_MODEL_PROVIDER": "deterministic",
        "PIPI_CARD_COMPOSER": "deterministic",
        "LLM_SHADOW_ENABLED": "false",
        "LLM_REWRITE_ENABLED": "false",
        "WEB_SEARCH_PROVIDER": "disabled",
    }
    previous = {key: os.environ.get(key) for key in updates}
    try:
        os.environ.update(updates)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _render_summary_markdown(summary: Mapping[str, Any]) -> str:
    guard = summary.get("guard") if isinstance(summary.get("guard"), Mapping) else {}
    stats = summary.get("stats") if isinstance(summary.get("stats"), Mapping) else {}
    latency = stats.get("latency") if isinstance(stats.get("latency"), Mapping) else {}
    coverage = summary.get("benchmark_coverage") if isinstance(summary.get("benchmark_coverage"), Mapping) else {}
    lines = [
        "# Product Benchmark Summary",
        "",
        f"- OK: `{bool(summary.get('ok'))}`",
        f"- Evaluated cases: `{int(summary.get('evaluated_cases') or 0)}`",
        f"- Suite: `{coverage.get('suite_id') or 'unknown'}`",
        f"- Target case count: `{_display(coverage.get('target_case_count'))}`",
        f"- Benchmark case count: `{_display(coverage.get('case_count'))}`",
        f"- Coverage complete: `{bool(coverage.get('coverage_complete'))}`",
        f"- Limited run: `{bool(coverage.get('is_limited_run'))}`",
        f"- Results path: `{summary.get('results_path')}`",
        f"- Rows with latency: `{int(guard.get('latency_rows') or 0)}`",
        f"- Runtime gate failed rows: `{int(_runtime_gate(summary).get('failed_rows') or 0)}`",
        f"- P50 latency: `{_display(latency.get('p50_ms'))}` ms",
        f"- P95 latency: `{_display(latency.get('p95_ms'))}` ms",
        f"- Max latency: `{_display(latency.get('max_ms'))}` ms",
        "",
    ]
    if coverage:
        by_category = coverage.get("by_category") if isinstance(coverage.get("by_category"), Mapping) else {}
        evaluated_by_category = (
            coverage.get("evaluated_by_category")
            if isinstance(coverage.get("evaluated_by_category"), Mapping)
            else {}
        )
        lines += ["## Benchmark Coverage", ""]
        if by_category:
            lines += ["| Category | Cases | Evaluated |", "| --- | ---: | ---: |"]
            for category, count in sorted(by_category.items()):
                lines.append(f"| `{category}` | {count} | {evaluated_by_category.get(category, 0)} |")
            lines.append("")
        else:
            lines += ["None.", ""]
    runtime_gate = _runtime_gate(summary)
    failure_samples = runtime_gate.get("failure_samples")
    if isinstance(failure_samples, list) and failure_samples:
        lines += [
            "## Runtime Gate Failures",
            "",
            "| Case | Category | Status | HTTP | Runtime Path | Issues |",
            "| --- | --- | --- | ---: | --- | --- |",
        ]
        for item in failure_samples:
            row = item if isinstance(item, Mapping) else {}
            issues = ", ".join(str(value) for value in (row.get("issues") or []))
            lines.append(
                f"| `{row.get('case_id')}` | `{row.get('category')}` | `{row.get('status')}` | "
                f"{row.get('status_code')} | `{row.get('runtime_path')}` | {issues} |"
            )
        lines.append("")
    for title, key in (
        ("Status Codes", "status_code_counts"),
        ("Response Kinds", "response_kind_counts"),
        ("Runtime Paths", "runtime_path_counts"),
    ):
        counts = stats.get(key) if isinstance(stats.get(key), Mapping) else {}
        lines += [f"## {title}", ""]
        if not counts:
            lines += ["None.", ""]
            continue
        lines += ["| Value | Count |", "| --- | ---: |"]
        for value, count in sorted(counts.items()):
            lines.append(f"| `{value}` | {count} |")
        lines.append("")
    slowest = stats.get("slowest_cases") if isinstance(stats.get("slowest_cases"), list) else []
    lines += ["## Slowest Cases", ""]
    if not slowest:
        lines.append("None.")
        return "\n".join(lines)
    lines += ["| Case | Category | Latency | Kind | Status |", "| --- | --- | ---: | --- | ---: |"]
    for item in slowest:
        row = item if isinstance(item, Mapping) else {}
        lines.append(
            f"| `{row.get('case_id')}` | `{row.get('category')}` | "
            f"{_display(row.get('latency_ms'))} | `{row.get('response_kind')}` | "
            f"{row.get('status_code')} |"
        )
    return "\n".join(lines)


def _runtime_gate(summary: Mapping[str, Any]) -> Mapping[str, Any]:
    value = summary.get("runtime_gate")
    return value if isinstance(value, Mapping) else {}


def _render_blocked_summary_markdown(summary: Mapping[str, Any]) -> str:
    blocker = summary.get("blocker") if isinstance(summary.get("blocker"), Mapping) else {}
    lines = [
        "# Product Benchmark Summary",
        "",
        "- Status: `blocked`",
        f"- Evaluated cases: `{int(summary.get('evaluated_cases') or 0)}`",
        f"- Results path: `{summary.get('results_path')}`",
        f"- Blocker code: `{blocker.get('code')}`",
        f"- Blocker message: {blocker.get('message')}",
    ]
    if blocker.get("error"):
        lines.append(f"- Error: `{blocker.get('error')}`")
    lines += [
        "",
        "Start the database or use `./scripts/test.sh` for the managed integration test path, then rerun the benchmark.",
    ]
    return "\n".join(lines) + "\n"


def _benchmark_coverage_summary(
    *,
    benchmark_path: Path,
    rows: Sequence[Mapping[str, Any]],
    total_case_count: int,
    limit: int | None,
) -> dict[str, Any]:
    payload = _safe_benchmark_payload(benchmark_path)
    cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    expected_distribution = payload.get("expected_distribution")
    expected_distribution = expected_distribution if isinstance(expected_distribution, Mapping) else {}
    target_case_count = payload.get("target_case_count")
    by_category = Counter(str(case.get("category") or "unknown") for case in cases if isinstance(case, Mapping))
    evaluated_by_category = Counter(str(row.get("category") or row.get("group") or "unknown") for row in rows)
    return {
        "suite_id": str(payload.get("suite_id") or _suite_id(benchmark_path)),
        "target_case_count": target_case_count,
        "case_count": total_case_count,
        "evaluated_case_count": len(rows),
        "is_limited_run": limit is not None,
        "coverage_complete": limit is None
        and len(rows) == total_case_count
        and (target_case_count is None or total_case_count == _safe_int(target_case_count)),
        "runtime_path_required": "product",
        "by_category": dict(sorted(by_category.items())),
        "evaluated_by_category": dict(sorted(evaluated_by_category.items())),
        "expected_distribution": dict(expected_distribution),
    }


def _safe_benchmark_payload(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _display(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def _parse_args(argv: Iterable[str] | None = None) -> ProductBenchmarkConfig:
    parser = argparse.ArgumentParser(description="Run Pipi product benchmark turns.")
    parser.add_argument("--benchmark", required=True, help="Benchmark suite JSON/YAML/JSONL path.")
    parser.add_argument("--out", required=True, help="Output report directory.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum cases to evaluate.")
    parser.add_argument("--run-id", default=None, help="Optional stable run id for report rows.")
    parser.add_argument(
        "--no-reports",
        action="store_true",
        help="Only write results and results guard report.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    return ProductBenchmarkConfig(
        benchmark_path=Path(args.benchmark).resolve(),
        output_dir=Path(args.out).resolve(),
        limit=args.limit,
        generate_reports=not args.no_reports,
        run_id=args.run_id,
    )


def main(argv: Iterable[str] | None = None) -> int:
    config = _parse_args(argv)
    try:
        summary = asyncio.run(run_product_benchmark(config))
    except Exception as exc:
        print(f"product benchmark failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
