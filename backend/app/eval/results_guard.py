"""Validation guard for evaluated benchmark result files."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from app.eval.reporting import load_json_or_jsonl


def validate_benchmark_results(
    results_path: str | Path,
    *,
    require_latency_ms: bool = False,
) -> dict[str, Any]:
    rows = load_json_or_jsonl(results_path)
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise ValueError("Results file must be a JSON array or JSONL rows.")
    mapping_rows = [dict(row) for row in rows if isinstance(row, Mapping)]
    if not mapping_rows:
        raise ValueError("results file contains zero evaluated cases")

    errors: list[dict[str, Any]] = []
    latency_count = 0
    for index, row in enumerate(mapping_rows, start=1):
        case_id = _case_id(row)
        row_errors = _row_errors(row, require_latency_ms=require_latency_ms)
        if _latency_ms(row) is not None:
            latency_count += 1
        for error in row_errors:
            errors.append({"row": index, "case_id": case_id, "error": error})

    result = {
        "ok": not errors,
        "results_path": str(Path(results_path)),
        "total_rows": len(mapping_rows),
        "latency_rows": latency_count,
        "require_latency_ms": require_latency_ms,
        "errors": errors,
    }
    if errors:
        raise ValueError(_error_message(result))
    return result


def write_results_guard_report(result: Mapping[str, Any], output_dir: str | Path) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "results_guard_report.json"
    md_path = output / "results_guard_report.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_results_guard_markdown(result), encoding="utf-8")
    return {"results_guard_json": json_path, "results_guard_markdown": md_path}


def render_results_guard_markdown(result: Mapping[str, Any]) -> str:
    errors = [dict(item) for item in _sequence(result.get("errors"))]
    lines = [
        "# Pipi Benchmark Results Guard",
        "",
        f"- Result: `{'passed' if result.get('ok') else 'failed'}`",
        f"- Results file: `{result.get('results_path')}`",
        f"- Total rows: `{result.get('total_rows', 0)}`",
        f"- Rows with latency: `{result.get('latency_rows', 0)}`",
        f"- Require latency: `{str(bool(result.get('require_latency_ms'))).lower()}`",
        "",
    ]
    if not errors:
        lines.append("No schema issues found.")
        return "\n".join(lines)
    lines += ["## Errors", "", "| Row | Case | Error |", "| ---: | --- | --- |"]
    for error in errors:
        lines.append(
            f"| {error.get('row')} | `{error.get('case_id')}` | `{error.get('error')}` |"
        )
    return "\n".join(lines)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate pipi benchmark result rows.")
    parser.add_argument("--results", required=True, help="Benchmark result JSON or JSONL file.")
    parser.add_argument("--out", help="Optional report output directory.")
    parser.add_argument("--require-latency-ms", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        result = validate_benchmark_results(
            args.results,
            require_latency_ms=args.require_latency_ms,
        )
    except ValueError as exc:
        result = _result_from_error(args.results, str(exc), args.require_latency_ms)
        if args.out:
            paths = write_results_guard_report(result, args.out)
            for name, path in paths.items():
                print(f"{name}: {path}")
        print(str(exc))
        return 2
    if args.out:
        paths = write_results_guard_report(result, args.out)
        for name, path in paths.items():
            print(f"{name}: {path}")
    else:
        print(json.dumps(result, ensure_ascii=False))
    return 0


def _row_errors(row: Mapping[str, Any], *, require_latency_ms: bool) -> list[str]:
    errors: list[str] = []
    if not _case_id(row):
        errors.append("case_id_missing")
    if not _message(row):
        errors.append("message_missing")
    if not _has_response(row):
        errors.append("response_missing")
    if require_latency_ms and _latency_ms(row) is None:
        errors.append("latency_ms_missing")
    return errors


def _case_id(row: Mapping[str, Any]) -> str:
    case = row.get("case")
    case = case if isinstance(case, Mapping) else {}
    return str(row.get("case_id") or row.get("id") or case.get("id") or "").strip()


def _message(row: Mapping[str, Any]) -> str:
    case = row.get("case")
    case = case if isinstance(case, Mapping) else {}
    return str(
        row.get("message")
        or row.get("input")
        or case.get("message")
        or case.get("input")
        or ""
    ).strip()


def _has_response(row: Mapping[str, Any]) -> bool:
    response = row.get("response")
    if isinstance(response, Mapping):
        return True
    status_code = row.get("status_code")
    if isinstance(status_code, int):
        return True
    return False


def _latency_ms(row: Mapping[str, Any]) -> float | None:
    value = row.get("latency_ms")
    if value is None:
        metadata = row.get("metadata")
        if isinstance(metadata, Mapping):
            value = metadata.get("latency_ms")
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _error_message(result: Mapping[str, Any]) -> str:
    errors = [dict(item) for item in _sequence(result.get("errors"))]
    samples = ", ".join(
        f"row={item.get('row')} case={item.get('case_id')} error={item.get('error')}"
        for item in errors[:5]
    )
    return f"benchmark results guard failed: {len(errors)} issue(s); {samples}"


def _result_from_error(results_path: str | Path, error: str, require_latency_ms: bool) -> dict[str, Any]:
    return {
        "ok": False,
        "results_path": str(Path(results_path)),
        "total_rows": 0,
        "latency_rows": 0,
        "require_latency_ms": require_latency_ms,
        "errors": [{"row": None, "case_id": None, "error": error}],
    }


def _sequence(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


if __name__ == "__main__":
    raise SystemExit(main())
