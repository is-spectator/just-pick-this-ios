"""Release-quality gate for Pipi benchmark reports."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any


P0_ISSUE_CODES = {
    "response_missing",
    "response_kind_mismatch",
    "location_state_mismatch",
    "target_type_mismatch",
    "tool_call_name_mismatch",
    "recommendation_card_missing",
    "help_card_missing",
}


def evaluate_quality_gate(
    report_dir: str | Path,
    *,
    min_pass_rate: float = 0.95,
    min_average_quality: float = 0.82,
    max_p0: int = 0,
    max_p1: int = 0,
    max_seed_gaps: int | None = None,
    min_shadow_schema_valid_rate: float | None = None,
    max_p50_latency_ms: float | None = None,
    max_p95_latency_ms: float | None = None,
) -> dict[str, Any]:
    report_path = Path(report_dir)
    quality_report = _load_json(report_path / "quality_report.json")
    summary = _mapping(quality_report.get("summary"))
    cases = [_mapping(item) for item in _sequence(quality_report.get("cases"))]
    p0_cases = [case for case in cases if _case_priority(case) == "P0"]
    p1_cases = [case for case in cases if _case_priority(case) == "P1"]
    seed_gap_cases = [
        case for case in cases if str(case.get("report_bucket") or "") == "seed_gap"
    ]

    pass_rate = _float(summary.get("pass_rate"))
    average_quality = _float(summary.get("average_quality_score"))
    checks = [
        _check(
            "pass_rate",
            pass_rate >= min_pass_rate,
            observed=pass_rate,
            threshold=min_pass_rate,
        ),
        _check(
            "average_quality_score",
            average_quality >= min_average_quality,
            observed=average_quality,
            threshold=min_average_quality,
        ),
        _check("p0_cases", len(p0_cases) <= max_p0, observed=len(p0_cases), threshold=max_p0),
        _check("p1_cases", len(p1_cases) <= max_p1, observed=len(p1_cases), threshold=max_p1),
    ]
    if max_seed_gaps is not None:
        checks.append(
            _check(
                "seed_gap_cases",
                len(seed_gap_cases) <= max_seed_gaps,
                observed=len(seed_gap_cases),
                threshold=max_seed_gaps,
            )
        )

    latency_stats = _latency_stats(cases)
    if max_p50_latency_ms is not None:
        p50_latency = latency_stats.get("p50_ms")
        checks.append(
            _check(
                "p50_latency_ms",
                p50_latency is not None and p50_latency <= max_p50_latency_ms,
                observed=p50_latency,
                threshold=max_p50_latency_ms,
            )
        )
    if max_p95_latency_ms is not None:
        p95_latency = latency_stats.get("p95_ms")
        checks.append(
            _check(
                "p95_latency_ms",
                p95_latency is not None and p95_latency <= max_p95_latency_ms,
                observed=p95_latency,
                threshold=max_p95_latency_ms,
            )
        )

    shadow_summary = _shadow_summary(report_path)
    if min_shadow_schema_valid_rate is not None and shadow_summary:
        shadow_rate = _shadow_schema_valid_rate(shadow_summary)
        checks.append(
            _check(
                "shadow_schema_valid_rate",
                shadow_rate >= min_shadow_schema_valid_rate,
                observed=shadow_rate,
                threshold=min_shadow_schema_valid_rate,
            )
        )
        checks.append(
            _check(
                "shadow_provider_errors",
                int(shadow_summary.get("provider_error_count") or 0) == 0,
                observed=int(shadow_summary.get("provider_error_count") or 0),
                threshold=0,
            )
        )
        checks.append(
            _check(
                "shadow_timeouts",
                int(shadow_summary.get("timeout_count") or 0) == 0,
                observed=int(shadow_summary.get("timeout_count") or 0),
                threshold=0,
            )
        )

    passed = all(bool(item["passed"]) for item in checks)
    result = {
        "passed": passed,
        "report_dir": str(report_path),
        "summary": {
            "pass_rate": pass_rate,
            "average_quality_score": average_quality,
            "p0_count": len(p0_cases),
            "p1_count": len(p1_cases),
            "seed_gap_count": len(seed_gap_cases),
            "latency_case_count": latency_stats.get("count", 0),
            "p50_latency_ms": latency_stats.get("p50_ms"),
            "p95_latency_ms": latency_stats.get("p95_ms"),
            "shadow_schema_valid_rate": _shadow_schema_valid_rate(shadow_summary)
            if shadow_summary
            else None,
        },
        "thresholds": {
            "min_pass_rate": min_pass_rate,
            "min_average_quality": min_average_quality,
            "max_p0": max_p0,
            "max_p1": max_p1,
            "max_seed_gaps": max_seed_gaps,
            "min_shadow_schema_valid_rate": min_shadow_schema_valid_rate,
            "max_p50_latency_ms": max_p50_latency_ms,
            "max_p95_latency_ms": max_p95_latency_ms,
        },
        "checks": checks,
        "p0_cases": [_case_gate_payload(case) for case in p0_cases],
        "p1_cases": [_case_gate_payload(case) for case in p1_cases],
        "seed_gap_cases": [_case_gate_payload(case) for case in seed_gap_cases],
        "latency_stats": latency_stats,
        "shadow_summary": shadow_summary,
    }
    _write_gate_reports(report_path, result)
    return result


def render_quality_gate_markdown(result: Mapping[str, Any]) -> str:
    lines = [
        "# Pipi Quality Gate Report",
        "",
        f"- Result: `{'passed' if result.get('passed') else 'failed'}`",
        f"- Report dir: `{result.get('report_dir')}`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    summary = _mapping(result.get("summary"))
    for key in (
        "pass_rate",
        "average_quality_score",
        "p0_count",
        "p1_count",
        "seed_gap_count",
        "latency_case_count",
        "p50_latency_ms",
        "p95_latency_ms",
        "shadow_schema_valid_rate",
    ):
        value = summary.get(key)
        lines.append(f"| `{key}` | {_display_value(value)} |")
    lines += [
        "",
        "## Checks",
        "",
        "| Check | Passed | Observed | Threshold |",
        "| --- | --- | ---: | ---: |",
    ]
    for check in _sequence(result.get("checks")):
        item = _mapping(check)
        lines.append(
            f"| `{item.get('name')}` | `{str(bool(item.get('passed'))).lower()}` | "
            f"{_display_value(item.get('observed'))} | {_display_value(item.get('threshold'))} |"
        )
    lines += ["", "## Blocking Cases", ""]
    for title, key in (("P0", "p0_cases"), ("P1", "p1_cases")):
        cases = [_mapping(item) for item in _sequence(result.get(key))]
        lines += [f"### {title}", ""]
        if not cases:
            lines.append("None.")
            lines.append("")
            continue
        lines += ["| Case | Score | Bucket | Issues |", "| --- | ---: | --- | --- |"]
        for case in cases:
            issue_text = ", ".join(f"`{issue}`" for issue in _sequence(case.get("issues"))) or "-"
            lines.append(
                f"| `{case.get('case_id')}` | {_display_value(case.get('quality_score'))} | "
                f"`{case.get('report_bucket')}` | {issue_text} |"
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Pipi quality gate reports.")
    parser.add_argument("--report-dir", required=True, help="Directory containing quality_report.json.")
    parser.add_argument("--min-pass-rate", type=float, default=0.95)
    parser.add_argument("--min-average-quality", type=float, default=0.82)
    parser.add_argument("--max-p0", type=int, default=0)
    parser.add_argument("--max-p1", type=int, default=0)
    parser.add_argument("--max-seed-gaps", type=int)
    parser.add_argument("--min-shadow-schema-valid-rate", type=float)
    parser.add_argument("--max-p50-latency-ms", type=float)
    parser.add_argument("--max-p95-latency-ms", type=float)
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = evaluate_quality_gate(
        args.report_dir,
        min_pass_rate=args.min_pass_rate,
        min_average_quality=args.min_average_quality,
        max_p0=args.max_p0,
        max_p1=args.max_p1,
        max_seed_gaps=args.max_seed_gaps,
        min_shadow_schema_valid_rate=args.min_shadow_schema_valid_rate,
        max_p50_latency_ms=args.max_p50_latency_ms,
        max_p95_latency_ms=args.max_p95_latency_ms,
    )
    print(f"quality_gate_json: {Path(args.report_dir) / 'quality_gate_report.json'}")
    print(f"quality_gate_markdown: {Path(args.report_dir) / 'quality_gate_report.md'}")
    return 0 if result["passed"] else 2


def _write_gate_reports(report_dir: Path, result: Mapping[str, Any]) -> None:
    (report_dir / "quality_gate_report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (report_dir / "quality_gate_report.md").write_text(
        render_quality_gate_markdown(result),
        encoding="utf-8",
    )


def _case_priority(case: Mapping[str, Any]) -> str:
    codes = set(str(code) for code in _case_issue_codes(case))
    if codes & P0_ISSUE_CODES:
        return "P0"
    if str(case.get("report_bucket") or "") == "seed_gap":
        return "P1"
    if _sequence(case.get("errors")):
        return "P1"
    if str(case.get("status") or "") != "passed":
        return "P2"
    return "passed"


def _case_issue_codes(case: Mapping[str, Any]) -> list[str]:
    codes: list[str] = []
    for issue in _sequence(case.get("issues")):
        mapped = _mapping(issue)
        code = str(mapped.get("code") or "").strip()
        if code:
            codes.append(code)
    return codes


def _case_gate_payload(case: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case.get("case_id"),
        "quality_score": case.get("quality_score"),
        "status": case.get("status"),
        "expected_kind": case.get("expected_kind"),
        "actual_kind": case.get("actual_kind"),
        "report_bucket": case.get("report_bucket"),
        "issues": _case_issue_codes(case),
    }


def _latency_stats(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = sorted(
        value
        for value in (_latency_ms(case) for case in cases)
        if value is not None and value >= 0
    )
    if not values:
        return {"count": 0, "p50_ms": None, "p95_ms": None}
    return {
        "count": len(values),
        "p50_ms": _percentile(values, 50),
        "p95_ms": _percentile(values, 95),
    }


def _latency_ms(case: Mapping[str, Any]) -> float | None:
    metadata = _mapping(case.get("metadata"))
    value = metadata.get("latency_ms")
    if value is None:
        value = case.get("latency_ms")
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _percentile(values: Sequence[float], percentile: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return round(values[0], 4)
    rank = (len(values) - 1) * (percentile / 100)
    lower = int(rank)
    upper = min(lower + 1, len(values) - 1)
    fraction = rank - lower
    observed = values[lower] + (values[upper] - values[lower]) * fraction
    return round(observed, 4)


def _shadow_summary(report_dir: Path) -> dict[str, Any]:
    path = report_dir / "shadow_comparison_report.json"
    if not path.exists():
        return {}
    payload = _load_json(path)
    return dict(_mapping(payload.get("summary")))


def _shadow_schema_valid_rate(summary: Mapping[str, Any]) -> float | None:
    total = int(summary.get("shadow_enabled_count") or summary.get("total_cases_with_shadow") or 0)
    if total <= 0:
        return None
    valid = int(summary.get("schema_valid_count") or 0)
    return round(valid / total, 4)


def _check(name: str, passed: bool, *, observed: Any, threshold: Any) -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "observed": observed,
        "threshold": threshold,
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing required report file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"Report file must contain a JSON object: {path}")
    return dict(payload)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list[Any]:
    if isinstance(value, list | tuple):
        return list(value)
    return []


def _float(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def _display_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
