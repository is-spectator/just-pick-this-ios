#!/usr/bin/env python3
"""Run local product turns with LLM shadow mode and write non-empty reports."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.eval.reporting import (  # noqa: E402
    generate_quality_reports_from_files,
    load_benchmark_cases,
)
from app.main import create_app  # noqa: E402
from app.models import AgentRun  # noqa: E402
from app.services.runtime import session_scope  # noqa: E402


SHADOW_PRODUCT_KINDS = {"recommendation_card", "help_card_draft"}


@dataclass(frozen=True)
class ShadowBenchmarkConfig:
    benchmark_path: Path
    output_dir: Path
    limit: int | None = None
    shadow_provider: str = "mock_shadow"
    min_schema_valid_rate: float = 0.98
    include_no_shadow: bool = False


async def run_shadow_benchmark(config: ShadowBenchmarkConfig) -> dict[str, Any]:
    cases = load_benchmark_cases(config.benchmark_path)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    results_path = config.output_dir / "shadow_results.jsonl"
    rows: list[dict[str, Any]] = []
    skipped_expected_direct = 0
    skipped_without_shadow = 0

    with _shadow_env(config.shadow_provider):
        get_settings.cache_clear()
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
                    if not config.include_no_shadow and not _case_is_shadow_product_case(case):
                        skipped_expected_direct += 1
                        continue

                    row = await _run_case(client, case=case, suite_id=_suite_id(config.benchmark_path))
                    if not config.include_no_shadow and not _row_has_shadow(row):
                        skipped_without_shadow += 1
                        continue
                    rows.append(row)
                    output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                    output.flush()

    get_settings.cache_clear()

    if not rows:
        raise RuntimeError("shadow benchmark produced zero evaluated rows")

    report_paths = generate_quality_reports_from_files(
        results_path=results_path,
        output_dir=config.output_dir,
        benchmark_path=config.benchmark_path,
    )
    shadow_report = json.loads(
        report_paths["shadow_comparison_json"].read_text(encoding="utf-8")
    )
    gate = validate_shadow_gate(
        shadow_report,
        expected_case_count=len(rows),
        min_schema_valid_rate=config.min_schema_valid_rate,
    )
    summary = {
        "ok": gate["ok"],
        "benchmark": str(config.benchmark_path),
        "output_dir": str(config.output_dir),
        "results_path": str(results_path),
        "evaluated_cases": len(rows),
        "skipped_expected_direct_cases": skipped_expected_direct,
        "skipped_without_shadow_cases": skipped_without_shadow,
        "shadow_provider": config.shadow_provider,
        "min_schema_valid_rate": config.min_schema_valid_rate,
        "gate": gate,
        "report_paths": {key: str(value) for key, value in report_paths.items()},
    }
    (config.output_dir / "shadow_benchmark_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (config.output_dir / "shadow_benchmark_summary.md").write_text(
        _render_summary_markdown(summary),
        encoding="utf-8",
    )
    if not gate["ok"]:
        raise RuntimeError("; ".join(gate["failures"]))
    return summary


def validate_shadow_gate(
    shadow_report: Mapping[str, Any],
    *,
    expected_case_count: int,
    min_schema_valid_rate: float = 0.98,
) -> dict[str, Any]:
    summary = dict(shadow_report.get("summary") or {})
    total_cases = int(summary.get("total_cases_with_shadow") or 0)
    enabled_count = int(summary.get("shadow_enabled_count") or 0)
    schema_valid_count = int(summary.get("schema_valid_count") or 0)
    schema_errors = int(summary.get("schema_error_count") or 0)
    provider_errors = int(summary.get("provider_error_count") or 0)
    timeouts = int(summary.get("timeout_count") or 0)
    mismatch_count = int(
        summary.get("deterministic_vs_shadow_mismatch_count")
        or summary.get("deterministic_shadow_mismatch_count")
        or 0
    )
    schema_valid_rate = round(schema_valid_count / enabled_count, 4) if enabled_count else 0.0
    failures: list[str] = []
    if expected_case_count <= 0:
        failures.append("expected_case_count_must_be_positive")
    if total_cases != expected_case_count:
        failures.append(
            f"shadow_case_count_mismatch expected={expected_case_count} actual={total_cases}"
        )
    if enabled_count != expected_case_count:
        failures.append(
            f"shadow_enabled_count_mismatch expected={expected_case_count} actual={enabled_count}"
        )
    if schema_valid_rate < min_schema_valid_rate:
        failures.append(
            f"shadow_schema_valid_rate_too_low threshold={min_schema_valid_rate} actual={schema_valid_rate}"
        )
    if provider_errors:
        failures.append(f"shadow_provider_errors_present count={provider_errors}")
    if timeouts:
        failures.append(f"shadow_timeouts_present count={timeouts}")
    return {
        "ok": not failures,
        "total_cases": total_cases,
        "shadow_enabled_cases": enabled_count,
        "shadow_success": schema_valid_count,
        "shadow_schema_errors": schema_errors,
        "shadow_provider_errors": provider_errors,
        "shadow_timeouts": timeouts,
        "shadow_schema_valid_rate": schema_valid_rate,
        "decision_mismatch_count": mismatch_count,
        "failures": failures,
    }


async def _run_case(
    client: AsyncClient,
    *,
    case: Mapping[str, Any],
    suite_id: str,
) -> dict[str, Any]:
    case_id = _case_id(case)
    message = str(case.get("message") or case.get("input") or "").strip()
    device_uid = f"shadow-bench-{case_id}-{uuid.uuid4()}"
    started = time.perf_counter()

    bootstrap_response = await client.post(
        "/v1/bootstrap",
        json={
            "device_uid": device_uid,
            "platform": "shadow-benchmark",
            "app_version": "0.1.0",
            "metadata": {"source": "run_shadow_benchmark"},
        },
    )
    if bootstrap_response.status_code != 200:
        latency_ms = _elapsed_ms(started)
        return {
            "case_id": case_id,
            "category": _case_group(case),
            "group": _case_group(case),
            "input": message,
            "message": message,
            "expected": dict(case.get("expected") or {}),
            "case": dict(case),
            "status_code": bootstrap_response.status_code,
            "latency_ms": latency_ms,
            "response": _safe_response_json(bootstrap_response),
            "error": "bootstrap_failed",
        }

    conversation_id = str(bootstrap_response.json().get("conversation_id") or "")
    response = await client.post(
        "/v1/chat/turn",
        json={
            "device_uid": device_uid,
            "conversation_id": conversation_id,
            "message": message,
            "client_context": {
                "source": "run_shadow_benchmark",
                "benchmark_suite_id": suite_id,
                "benchmark_case_id": case_id,
                "benchmark_group": _case_group(case),
                "include_debug": False,
                "mode": "shadow_benchmark",
            },
            "metadata": {
                "benchmark_case_id": case_id,
                "benchmark_group": _case_group(case),
            },
        },
    )
    latency_ms = _elapsed_ms(started)
    body = _safe_response_json(response)
    metadata = body.get("metadata") if isinstance(body, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else {}
    agent_run_id = str(metadata.get("agent_run_id") or "")
    output_json = _agent_run_output(agent_run_id)
    shadow_results = _shadow_reasoner_results(output_json)
    shadow_result = shadow_results[-1] if shadow_results else {}
    actual_summary = _actual_summary(body if isinstance(body, dict) else {})
    return {
        "case_id": case_id,
        "category": _case_group(case),
        "group": _case_group(case),
        "input": message,
        "message": message,
        "expected": dict(case.get("expected") or {}),
        "case": dict(case),
        "status_code": response.status_code,
        "latency_ms": latency_ms,
        "response": body,
        "actual_summary": actual_summary,
        "agent_run_id": agent_run_id or None,
        "trace_id": agent_run_id or None,
        "metadata_loop_tool_calls": list(
            ((metadata.get("loop") if isinstance(metadata.get("loop"), dict) else {}) or {}).get("tool_calls")
            or []
        ),
        "shadow_summary": output_json.get("shadow_summary") if isinstance(output_json, dict) else None,
        "shadow_reasoner_results": shadow_results,
        "shadow_reasoner_result": shadow_result,
        "output_json": output_json,
    }


def _agent_run_output(agent_run_id: str) -> dict[str, Any]:
    if not agent_run_id:
        return {}
    try:
        with session_scope() as session:
            agent_run = session.get(AgentRun, uuid.UUID(agent_run_id))
            if agent_run is None:
                return {}
            return dict(agent_run.output_json or {})
    except Exception as exc:
        return {"agent_run_lookup_error": str(exc)}


def _shadow_reasoner_results(output_json: Mapping[str, Any]) -> list[dict[str, Any]]:
    results = output_json.get("shadow_reasoner_results")
    if isinstance(results, list):
        return [dict(item) for item in results if isinstance(item, Mapping)]
    trace = output_json.get("loop_trace")
    if not isinstance(trace, list):
        return []
    rows: list[dict[str, Any]] = []
    for event in trace:
        if not isinstance(event, Mapping) or event.get("event") != "shadow_reasoner_result":
            continue
        payload = event.get("payload") or event.get("data")
        if isinstance(payload, Mapping):
            rows.append(dict(payload))
    return rows


def _actual_summary(response: Mapping[str, Any]) -> dict[str, Any]:
    data = response.get("data") if isinstance(response.get("data"), Mapping) else {}
    card = data.get("recommendation_card") if isinstance(data.get("recommendation_card"), Mapping) else {}
    help_card = data.get("help_card") if isinstance(data.get("help_card"), Mapping) else {}
    target_type = card.get("target_type") or help_card.get("target_type")
    if not target_type:
        cards = response.get("cards")
        if isinstance(cards, Sequence) and not isinstance(cards, (str, bytes, bytearray)) and cards:
            first = cards[0] if isinstance(cards[0], Mapping) else {}
            target_type = first.get("target_type")
    return {
        "response_kind": response.get("response_kind"),
        "location_state": response.get("location_state"),
        "target_type": target_type or "none",
    }


def _case_is_shadow_product_case(case: Mapping[str, Any]) -> bool:
    expected = case.get("expected") if isinstance(case.get("expected"), Mapping) else {}
    expected_kind = str(
        expected.get("response_kind")
        or expected.get("kind")
        or case.get("expected_response_kind")
        or ""
    ).strip()
    return expected_kind in SHADOW_PRODUCT_KINDS


def _row_has_shadow(row: Mapping[str, Any]) -> bool:
    summary = row.get("shadow_summary")
    if isinstance(summary, Mapping) and bool(summary.get("enabled")):
        return True
    results = row.get("shadow_reasoner_results")
    return isinstance(results, Sequence) and not isinstance(results, (str, bytes, bytearray)) and bool(results)


def _case_id(case: Mapping[str, Any]) -> str:
    return str(case.get("id") or case.get("case_id") or uuid.uuid4()).strip()


def _case_group(case: Mapping[str, Any]) -> str:
    return str(case.get("category") or case.get("group") or "unknown").strip() or "unknown"


def _suite_id(benchmark_path: Path) -> str:
    # load_benchmark_cases intentionally returns only cases. Keep suite id stable
    # for trace metadata without reparsing a second time.
    return benchmark_path.stem


def _safe_response_json(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception:
        return {"raw_text": getattr(response, "text", "")}
    return payload if isinstance(payload, dict) else {"payload": payload}


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


@contextmanager
def _shadow_env(provider: str) -> Iterable[None]:
    updates = {
        "APP_ENV": "test",
        "PIPI_EVAL_MODE": "false",
        "ALLOW_EVAL_BYPASS": "false",
        "AUTO_SEED_ON_REQUEST": "false",
        "PIPI_MODEL_PROVIDER": "deterministic",
        "PIPI_CARD_COMPOSER": "deterministic",
        "LLM_SHADOW_ENABLED": "true",
        "LLM_PROVIDER": provider,
        "LLM_MODEL": "mock-shadow-v0" if provider.startswith("mock_shadow") else os.getenv("LLM_MODEL", "gpt-4.1-mini"),
        "WEB_SEARCH_PROVIDER": "disabled",
    }
    if provider.startswith("mock_shadow"):
        updates["OPENAI_API_KEY"] = ""
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
    gate = dict(summary.get("gate") or {})
    lines = [
        "# Shadow Benchmark Summary",
        "",
        f"- OK: `{bool(summary.get('ok'))}`",
        f"- Evaluated cases: `{int(summary.get('evaluated_cases') or 0)}`",
        f"- Skipped without shadow: `{int(summary.get('skipped_without_shadow_cases') or 0)}`",
        f"- Shadow provider: `{summary.get('shadow_provider')}`",
        f"- Schema valid rate: `{gate.get('shadow_schema_valid_rate', 0.0)}`",
        f"- Provider errors: `{gate.get('shadow_provider_errors', 0)}`",
        f"- Timeouts: `{gate.get('shadow_timeouts', 0)}`",
        f"- Decision mismatches: `{gate.get('decision_mismatch_count', 0)}`",
        "",
    ]
    failures = list(gate.get("failures") or [])
    if failures:
        lines += ["## Failures", ""]
        lines.extend(f"- `{failure}`" for failure in failures)
        lines.append("")
    return "\n".join(lines)


def _parse_args(argv: Iterable[str] | None = None) -> ShadowBenchmarkConfig:
    parser = argparse.ArgumentParser(description="Run Pipi product turns with LLM shadow mode.")
    parser.add_argument("--benchmark", required=True, help="Benchmark suite JSON/YAML/JSONL path.")
    parser.add_argument("--out", required=True, help="Output report directory.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum shadow-product cases to evaluate.")
    parser.add_argument(
        "--shadow-provider",
        choices=["mock_shadow", "openai"],
        default="mock_shadow",
    )
    parser.add_argument(
        "--min-schema-valid-rate",
        type=float,
        default=0.98,
    )
    parser.add_argument(
        "--include-no-shadow",
        action="store_true",
        help="Include direct-answer/clarification cases that may not enter PipiLoop shadow.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    return ShadowBenchmarkConfig(
        benchmark_path=Path(args.benchmark).resolve(),
        output_dir=Path(args.out).resolve(),
        limit=args.limit,
        shadow_provider=args.shadow_provider,
        min_schema_valid_rate=args.min_schema_valid_rate,
        include_no_shadow=args.include_no_shadow,
    )


def main(argv: Iterable[str] | None = None) -> int:
    config = _parse_args(argv)
    try:
        summary = asyncio.run(run_shadow_benchmark(config))
    except Exception as exc:
        print(f"shadow benchmark failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
