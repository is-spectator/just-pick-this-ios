"""Report writers for pipi benchmark quality scores."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from app.eval.quality_scoring import (
    CaseQualityScore,
    QUALITY_DIMENSIONS,
    QUALITY_SCORE_FORMULA,
    score_rows,
    summarize_scores,
)
from app.eval.agent_issue_generator import write_agent_fix_issue_reports
from app.eval.experiment_lift import write_experiment_lift_reports
from app.eval.quality_attribution import attribute_rows, summarize_attributions
from app.eval.seed_candidate_generator import write_seed_candidate_reports
from app.eval.shadow_promotion_generator import write_shadow_promotion_candidate_reports
from app.eval.shadow_quality import score_shadow_decision


DEFAULT_LOW_QUALITY_THRESHOLD = 0.75
_P0_ISSUE_CODES = {
    "response_missing",
    "response_kind_mismatch",
    "location_state_mismatch",
    "target_type_mismatch",
    "tool_call_name_mismatch",
    "recommendation_card_missing",
    "help_card_missing",
}
DEFAULT_BENCHMARK_DISTRIBUTION = {
    "by_category": {
        "area_food": 100,
        "edge_adversarial": 20,
        "help_card_update": 60,
        "one_liner_finalize": 40,
        "product_decision": 60,
        "smalltalk_app_help_unknown": 50,
        "travel_shopping": 80,
        "venue_order": 90,
    },
    "by_expected_kind": {
        "chitchat": 50,
        "clarification": 20,
        "help_card_draft": 140,
        "recommendation_card": 290,
    },
    "by_location_state": {
        "in_area": 160,
        "in_venue": 90,
        "unknown": 250,
    },
    "by_target_type": {
        "none": 210,
        "ordering_bundle": 90,
        "product": 60,
        "restaurant": 140,
    },
}


def load_json_or_jsonl(path: str | Path) -> Any:
    source = Path(path)
    if source.suffix == ".jsonl":
        return [
            json.loads(line)
            for line in source.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    if source.suffix in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:
            raise ValueError(
                "YAML benchmark files require PyYAML; use JSON/JSONL or install PyYAML."
            ) from exc
        return yaml.safe_load(source.read_text(encoding="utf-8"))
    return json.loads(source.read_text(encoding="utf-8"))


def load_benchmark_cases(path: str | Path) -> list[dict[str, Any]]:
    payload = load_json_or_jsonl(path)
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        cases = payload.get("cases")
        if isinstance(cases, Sequence) and not isinstance(cases, (str, bytes, bytearray)):
            return [dict(item) for item in cases if isinstance(item, Mapping)]
    raise ValueError(f"Benchmark file must be a JSON array, JSONL, or object with cases: {path}")


def validate_benchmark_cases(cases: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, case in enumerate(cases, start=1):
        case_id = str(case.get("id") or case.get("case_id") or "").strip()
        expected = case.get("expected") if isinstance(case.get("expected"), Mapping) else {}
        expected_kind = str(
            expected.get("response_kind")
            or expected.get("kind")
            or case.get("expected_response_kind")
            or ""
        ).strip()
        if not case_id:
            errors.append({"index": index, "code": "case_missing_id"})
        elif case_id in seen_ids:
            errors.append({"index": index, "case_id": case_id, "code": "case_duplicate_id"})
        else:
            seen_ids.add(case_id)
        if not str(case.get("message") or case.get("input") or "").strip():
            errors.append({"index": index, "case_id": case_id, "code": "case_missing_message"})
        if not expected_kind:
            errors.append({"index": index, "case_id": case_id, "code": "case_missing_expected_kind"})
    return errors


def benchmark_coverage(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_category: Counter[str] = Counter()
    by_expected_kind: Counter[str] = Counter()
    by_location_state: Counter[str] = Counter()
    by_target_type: Counter[str] = Counter()
    for case in cases:
        expected = case.get("expected") if isinstance(case.get("expected"), Mapping) else {}
        by_category[_clean(case.get("category") or case.get("group") or "uncategorized")] += 1
        by_expected_kind[
            _clean(expected.get("response_kind") or expected.get("kind") or "unknown")
        ] += 1
        by_location_state[
            _clean(expected.get("location_state") or case.get("location_state") or "unknown")
        ] += 1
        by_target_type[_clean(expected.get("target_type") or "none")] += 1
    validation_errors = validate_benchmark_cases(cases)
    expected_distribution = _expected_distribution(cases)
    actual_distribution = {
        "by_category": dict(sorted(by_category.items())),
        "by_expected_kind": dict(sorted(by_expected_kind.items())),
        "by_location_state": dict(sorted(by_location_state.items())),
        "by_target_type": dict(sorted(by_target_type.items())),
    }
    distribution_errors = _distribution_errors(actual_distribution, expected_distribution)
    return {
        "total_cases": len(cases),
        "schema_valid": not validation_errors,
        "validation_errors": validation_errors,
        "distribution_valid": not distribution_errors,
        "distribution_errors": distribution_errors,
        "expected_distribution": expected_distribution,
        **actual_distribution,
    }


def write_quality_reports(
    rows: Sequence[Mapping[str, Any]],
    output_dir: str | Path,
    *,
    benchmark_cases: Sequence[Mapping[str, Any]] | None = None,
    low_quality_threshold: float = DEFAULT_LOW_QUALITY_THRESHOLD,
    report_mode: str = "evaluated",
) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    scores = score_rows(rows)
    summary = summarize_scores(scores)
    attributions = attribute_rows(rows)
    attribution_summary = summarize_attributions(attributions)
    low_quality = [score for score in scores if score.quality_score < low_quality_threshold]
    seed_gap = [score for score in scores if is_seed_gap_case(score)]
    agent_improvement = [score for score in scores if is_agent_improvement_case(score)]
    coverage = benchmark_coverage(benchmark_cases or [])
    shadow_report = build_shadow_comparison_report(rows)
    evaluated_case_count = len(rows)
    benchmark_case_count = len(benchmark_cases or [])

    paths = {
        "summary_markdown": output / "summary.md",
        "quality_json": output / "quality_report.json",
        "quality_attribution_json": output / "quality_attribution.json",
        "quality_attribution_jsonl": output / "quality_attribution.jsonl",
        "quality_markdown": output / "quality_report.md",
        "case_scores_jsonl": output / "case_quality_scores.jsonl",
        "low_quality_markdown": output / "low_quality_cases.md",
        "seed_gap_markdown": output / "seed_gap_report.md",
        "seed_gap_json": output / "seed_gap_report.json",
        "agent_improvement_markdown": output / "pipi_agent_improvement_report.md",
        "coverage_markdown": output / "benchmark_coverage_report.md",
        "shadow_comparison_markdown": output / "shadow_comparison_report.md",
        "shadow_comparison_json": output / "shadow_comparison_report.json",
        "shadow_decisions_jsonl": output / "shadow_decisions.jsonl",
        "experiment_lift_markdown": output / "experiment_lift_report.md",
        "experiment_lift_json": output / "experiment_lift_report.json",
        "generated_issues_index": output / "generated" / "index.md",
        "generated_issues_p2_aggregate": output / "generated" / "p2_aggregate.md",
    }

    paths["quality_json"].write_text(
        json.dumps(
            {
                "summary": summary,
                "effect_attribution_summary": attribution_summary,
                "report_mode": report_mode,
                "evaluated_case_count": evaluated_case_count,
                "benchmark_case_count": benchmark_case_count,
                "low_quality_threshold": low_quality_threshold,
                "cases": [_score_payload(score) for score in scores],
                "seed_gap_cases": [score.case_id for score in seed_gap],
                "agent_improvement_cases": [score.case_id for score in agent_improvement],
                "coverage": coverage,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    paths["quality_attribution_json"].write_text(
        json.dumps(
            {"summary": attribution_summary, "cases": attributions},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    paths["quality_attribution_jsonl"].write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in attributions),
        encoding="utf-8",
    )
    paths["summary_markdown"].write_text(
        render_summary_markdown(
            report_mode=report_mode,
            evaluated_case_count=evaluated_case_count,
            benchmark_case_count=benchmark_case_count,
            summary=summary,
        ),
        encoding="utf-8",
    )
    paths["case_scores_jsonl"].write_text(
        "".join(
            json.dumps(_score_payload(score), ensure_ascii=False, sort_keys=True) + "\n"
            for score in scores
        ),
        encoding="utf-8",
    )
    paths["quality_markdown"].write_text(
        render_quality_report_markdown(
            summary,
            scores,
            low_quality_threshold,
            report_mode=report_mode,
            evaluated_case_count=evaluated_case_count,
        ),
        encoding="utf-8",
    )
    paths["low_quality_markdown"].write_text(
        render_low_quality_cases_markdown(low_quality, low_quality_threshold),
        encoding="utf-8",
    )
    paths["seed_gap_markdown"].write_text(
        render_seed_gap_report_markdown(seed_gap),
        encoding="utf-8",
    )
    paths["seed_gap_json"].write_text(
        json.dumps(
            {
                "total": len(seed_gap),
                "cases": [_score_payload(score) for score in seed_gap],
                "attribution_summary": attribution_summary,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    paths["agent_improvement_markdown"].write_text(
        render_agent_improvement_report_markdown(agent_improvement),
        encoding="utf-8",
    )
    paths["coverage_markdown"].write_text(
        render_benchmark_coverage_markdown(coverage),
        encoding="utf-8",
    )
    paths["shadow_comparison_json"].write_text(
        json.dumps(shadow_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    paths["shadow_comparison_markdown"].write_text(
        render_shadow_comparison_markdown(shadow_report, report_mode=report_mode),
        encoding="utf-8",
    )
    paths["shadow_decisions_jsonl"].write_text(
        "".join(
            json.dumps(_shadow_decision_jsonl_payload(decision), ensure_ascii=False) + "\n"
            for decision in shadow_report["decisions"]
        ),
        encoding="utf-8",
    )
    write_generated_issue_reports(scores, output / "generated")
    paths.update(write_experiment_lift_reports(rows, output))
    paths.update(write_shadow_promotion_candidate_reports(shadow_report, output))
    paths.update(write_seed_candidate_reports(rows, attributions, output))
    paths.update(write_agent_fix_issue_reports(attributions, output))
    return paths


def write_benchmark_coverage_report(
    benchmark_cases: Sequence[Mapping[str, Any]],
    output_dir: str | Path,
) -> Path:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    path = output / "benchmark_coverage_report.md"
    path.write_text(
        render_benchmark_coverage_markdown(benchmark_coverage(benchmark_cases)),
        encoding="utf-8",
    )
    return path


def write_generated_issue_reports(
    scores: Sequence[CaseQualityScore],
    output_dir: str | Path,
) -> dict[str, Path]:
    """Write executable benchmark-followup issues.

    P0/P1 cases get individual `issuer_*.md` files. P2 cases are grouped into
    one aggregate report to keep the generated backlog useful instead of noisy.
    """

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    existing_issue_files = list(output.glob("issuer_*.md"))
    for path in existing_issue_files:
        path.unlink()

    issue_candidates = [
        score
        for score in scores
        if is_seed_gap_case(score) or is_agent_improvement_case(score)
    ]
    individual_scores = [
        score for score in issue_candidates if _issue_priority(score) in {"P0", "P1"}
    ]
    p2_scores = [score for score in issue_candidates if _issue_priority(score) == "P2"]

    written: dict[str, Path] = {}
    for index, score in enumerate(
        sorted(
            individual_scores,
            key=lambda item: (
                _priority_rank(_issue_priority(item)),
                _issue_owner(item),
                item.quality_score,
                item.case_id,
            ),
        )
    ):
        path = output / f"issuer_{index:03d}.md"
        path.write_text(render_generated_issue_markdown(score, index=index), encoding="utf-8")
        written[f"issuer_{index:03d}"] = path

    index_path = output / "index.md"
    index_path.write_text(
        render_generated_issue_index_markdown(
            individual_scores=individual_scores,
            p2_scores=p2_scores,
        ),
        encoding="utf-8",
    )
    written["index"] = index_path

    p2_path = output / "p2_aggregate.md"
    p2_path.write_text(render_p2_aggregate_markdown(p2_scores), encoding="utf-8")
    written["p2_aggregate"] = p2_path
    return written


def render_quality_report_markdown(
    summary: Mapping[str, Any],
    scores: Sequence[CaseQualityScore],
    low_quality_threshold: float,
    *,
    report_mode: str = "evaluated",
    evaluated_case_count: int | None = None,
) -> str:
    lines = [
        "# Pipi Quality Report",
        "",
        f"- Report mode: `{report_mode}`",
        f"- Evaluated cases: `{evaluated_case_count if evaluated_case_count is not None else len(scores)}`",
        "",
    ]
    if report_mode == "coverage_only":
        lines += [
            "> This is coverage-only. No product runtime results were evaluated.",
            "",
        ]
    lines += [
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Total | {summary['total']} |",
        f"| Passed | {summary['passed']} |",
        f"| Degraded | {summary['degraded']} |",
        f"| Failed | {summary['failed']} |",
        f"| Pass rate | {_pct(summary['pass_rate'])} |",
        f"| Non-failed rate | {_pct(summary['non_failed_rate'])} |",
        f"| Average quality score | {summary['average_quality_score']:.4f} |",
        f"| Low-quality threshold | {low_quality_threshold:.2f} |",
        f"| Formula | `{summary.get('score_formula') or QUALITY_SCORE_FORMULA}` |",
        "",
        "## Quality Dimensions",
        "",
        "| Dimension | Average | Penalty Total |",
        "| --- | ---: | ---: |",
    ]
    average_dimensions = _mapping(summary.get("average_dimensions"))
    dimension_penalty_totals = _mapping(summary.get("dimension_penalty_totals"))
    for dimension in QUALITY_DIMENSIONS:
        lines.append(
            f"| `{dimension}` | {float(average_dimensions.get(dimension, 0.0)):.4f} | "
            f"{float(dimension_penalty_totals.get(dimension, 0.0)):.4f} |"
        )
    lines += [
        "",
        "## Top Issues",
        "",
    ]
    top_issues = list(summary.get("top_issues") or [])
    if top_issues:
        lines += ["| Issue | Count |", "| --- | ---: |"]
        lines += [f"| `{item['code']}` | {item['count']} |" for item in top_issues]
    else:
        lines.append("No issues.")
    lines += ["", "## Case Scores", "", "| Case | Status | Score | Actual | Issues |", "| --- | --- | ---: | --- | --- |"]
    for score in scores:
        issue_text = ", ".join(f"`{issue.code}`" for issue in score.issues) or "-"
        lines.append(
            f"| `{score.case_id}` | {score.status} | {score.quality_score:.4f} | "
            f"`{score.actual_kind}` | {issue_text} |"
        )
    return "\n".join(lines) + "\n"


def render_summary_markdown(
    *,
    report_mode: str,
    evaluated_case_count: int,
    benchmark_case_count: int,
    summary: Mapping[str, Any],
) -> str:
    lines = [
        "# Benchmark Report Summary",
        "",
        f"- report_mode: `{report_mode}`",
        f"- evaluated_case_count: `{evaluated_case_count}`",
        f"- benchmark_case_count: `{benchmark_case_count}`",
        f"- pass_rate: `{_pct(summary.get('pass_rate'))}`",
        f"- average_quality_score: `{float(summary.get('average_quality_score', 0.0)):.4f}`",
        "",
    ]
    if report_mode == "coverage_only":
        lines.append("This is coverage-only. No product runtime results were evaluated.")
    return "\n".join(lines) + "\n"


def render_low_quality_cases_markdown(
    scores: Sequence[CaseQualityScore],
    threshold: float,
) -> str:
    lines = [
        "# Low Quality Cases",
        "",
        f"Threshold: `{threshold:.2f}`",
        "",
    ]
    if not scores:
        lines.append("No cases below threshold.")
        return "\n".join(lines) + "\n"
    for score in sorted(scores, key=lambda item: (item.quality_score, item.case_id)):
        lines += [
            f"## `{score.case_id}`",
            "",
            f"- Status: `{score.status}`",
            f"- Score: `{score.quality_score:.4f}`",
            f"- Expected: `{score.expected_kind}`",
            f"- Actual: `{score.actual_kind}`",
            f"- Message: {score.metadata.get('message') or ''}",
            "",
            "| Issue | Severity | Penalty |",
            "| --- | --- | ---: |",
        ]
        for issue in score.issues:
            lines.append(f"| `{issue.code}` | {issue.severity} | {issue.penalty:.2f} |")
        lines.append("")
    return "\n".join(lines)


def render_seed_gap_report_markdown(scores: Sequence[CaseQualityScore]) -> str:
    lines = [
        "# Seed Gap Report",
        "",
        "Cases here expected a recommendation card, but the actual response was a help-card draft.",
        "That means the agent deferred instead of making an unsafe recommendation.",
        "",
    ]
    if not scores:
        lines.append("No seed gaps.")
        return "\n".join(lines) + "\n"
    lines += ["| Case | Score | Message | Issues |", "| --- | ---: | --- | --- |"]
    for score in sorted(scores, key=lambda item: item.case_id):
        lines.append(
            f"| `{score.case_id}` | {score.quality_score:.4f} | "
            f"{_escape_table(score.metadata.get('message') or '')} | "
            f"{_issue_text(score)} |"
        )
    return "\n".join(lines) + "\n"


def render_agent_improvement_report_markdown(scores: Sequence[CaseQualityScore]) -> str:
    lines = [
        "# Pipi Agent Improvement Report",
        "",
        "Cases here need agent or routing fixes. Seed-gap fallback cases are excluded.",
        "",
    ]
    if not scores:
        lines.append("No agent improvement cases.")
        return "\n".join(lines) + "\n"
    lines += [
        "| Case | Status | Score | Expected | Actual | Primary Issues |",
        "| --- | --- | ---: | --- | --- | --- |",
    ]
    for score in sorted(scores, key=lambda item: (item.status, item.quality_score, item.case_id)):
        lines.append(
            f"| `{score.case_id}` | {score.status} | {score.quality_score:.4f} | "
            f"`{score.expected_kind}` | `{score.actual_kind}` | {_issue_text(score)} |"
        )
    return "\n".join(lines) + "\n"


def render_benchmark_coverage_markdown(coverage: Mapping[str, Any]) -> str:
    lines = [
        "# Benchmark Coverage Report",
        "",
        f"- Total cases: `{coverage.get('total_cases', 0)}`",
        f"- Schema valid: `{str(bool(coverage.get('schema_valid'))).lower()}`",
        f"- Distribution valid: `{str(bool(coverage.get('distribution_valid'))).lower()}`",
        "",
    ]
    validation_errors = list(coverage.get("validation_errors") or [])
    if validation_errors:
        lines += ["## Schema Errors", "", "| Case | Code |", "| --- | --- |"]
        for error in validation_errors:
            case = error.get("case_id") or error.get("index") or "-"
            lines.append(f"| `{case}` | `{error.get('code')}` |")
        lines.append("")
    distribution_errors = list(coverage.get("distribution_errors") or [])
    if distribution_errors:
        lines += ["## Distribution Errors", "", "| Bucket | Expected | Actual |", "| --- | ---: | ---: |"]
        for error in distribution_errors:
            lines.append(
                f"| `{error.get('bucket')}` | {error.get('expected')} | {error.get('actual')} |"
            )
        lines.append("")
    for title, key in (
        ("Category", "by_category"),
        ("Expected Kind", "by_expected_kind"),
        ("Location State", "by_location_state"),
        ("Target Type", "by_target_type"),
    ):
        lines += [f"## {title}", "", "| Value | Cases |", "| --- | ---: |"]
        values = coverage.get(key) or {}
        if isinstance(values, Mapping) and values:
            for value, count in values.items():
                lines.append(f"| `{value}` | {count} |")
        else:
            lines.append("| `none` | 0 |")
        lines.append("")
    return "\n".join(lines)


def build_shadow_comparison_report(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    decisions = [
        _enrich_shadow_decision(decision)
        for row in rows
        if (decision := _shadow_decision_from_row(row)) is not None
    ]
    mismatch_by_group = Counter(
        str(decision.get("group") or "unknown")
        for decision in decisions
        if decision.get("mismatch")
    )
    top_mismatches = [
        {
            "case_id": decision["case_id"],
            "group": decision.get("group") or "unknown",
            "deterministic": decision.get("deterministic"),
            "shadow": decision.get("shadow"),
            "quality_delta": decision.get("quality_delta"),
            "unsafe_to_promote_reason": decision.get("unsafe_to_promote_reason"),
            "trace_id": decision.get("trace_id"),
        }
        for decision in sorted(
            (item for item in decisions if item.get("mismatch")),
            key=lambda item: (
                str(item.get("group") or "unknown"),
                str(item.get("case_id") or ""),
            ),
        )[:20]
    ]
    mismatch_count = sum(1 for item in decisions if item.get("mismatch"))
    summary = {
        "total_cases_with_shadow": len(decisions),
        "shadow_enabled_count": sum(1 for item in decisions if item.get("shadow_enabled")),
        "schema_valid_count": sum(1 for item in decisions if item.get("schema_valid")),
        "schema_error_count": sum(1 for item in decisions if item.get("schema_error")),
        "provider_error_count": sum(1 for item in decisions if item.get("provider_error")),
        "timeout_count": sum(1 for item in decisions if item.get("timeout")),
        "deterministic_vs_shadow_mismatch_count": mismatch_count,
        "deterministic_shadow_mismatch_count": mismatch_count,
        "better_shadow_count": sum(1 for item in decisions if float(item.get("quality_delta") or 0) > 0),
        "worse_shadow_count": sum(1 for item in decisions if float(item.get("quality_delta") or 0) < 0),
        "unsafe_shadow_count": sum(1 for item in decisions if item.get("unsafe")),
        "shadow_improvement_candidates": sum(
            1
            for item in decisions
            if item.get("schema_valid")
            and item.get("mismatch")
            and not item.get("unsafe")
            and float(item.get("quality_delta") or 0) > 0
        ),
    }
    top_unsafe = [
        {
            "case_id": decision["case_id"],
            "group": decision.get("group") or "unknown",
            "shadow": decision.get("shadow"),
            "reason": decision.get("unsafe_to_promote_reason"),
            "trace_id": decision.get("trace_id"),
        }
        for decision in decisions
        if decision.get("unsafe")
    ][:20]
    top_possible_improvements = [
        {
            "case_id": decision["case_id"],
            "group": decision.get("group") or "unknown",
            "deterministic": decision.get("deterministic"),
            "shadow": decision.get("shadow"),
            "quality_delta": decision.get("quality_delta"),
            "trace_id": decision.get("trace_id"),
        }
        for decision in sorted(
            (
                item
                for item in decisions
                if not item.get("unsafe") and float(item.get("quality_delta") or 0) > 0
            ),
            key=lambda item: float(item.get("quality_delta") or 0),
            reverse=True,
        )[:20]
    ]
    return {
        "summary": summary,
        "mismatch_by_group": dict(sorted(mismatch_by_group.items())),
        "top_20_mismatches": top_mismatches,
        "top_mismatches": top_mismatches,
        "top_unsafe_examples": top_unsafe,
        "top_possible_improvements": top_possible_improvements,
        "decisions": decisions,
    }


def render_shadow_comparison_markdown(
    report: Mapping[str, Any],
    *,
    report_mode: str = "evaluated",
) -> str:
    summary = _mapping(report.get("summary"))
    lines = [
        "# Shadow Comparison Report",
        "",
        f"- Report mode: `{report_mode}`",
        "",
    ]
    if report_mode == "coverage_only" or int(summary.get("total_cases_with_shadow", 0)) == 0:
        lines += [
            "No shadow decisions evaluated.",
            "",
        ]
    lines += [
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Total cases with shadow | {int(summary.get('total_cases_with_shadow', 0))} |",
        f"| Shadow enabled count | {int(summary.get('shadow_enabled_count', 0))} |",
        f"| Schema valid count | {int(summary.get('schema_valid_count', 0))} |",
        f"| Schema error count | {int(summary.get('schema_error_count', 0))} |",
        f"| Provider error count | {int(summary.get('provider_error_count', 0))} |",
        f"| Timeout count | {int(summary.get('timeout_count', 0))} |",
        (
            "| Deterministic vs shadow mismatch count | "
            f"{int(summary.get('deterministic_vs_shadow_mismatch_count', 0))} |"
        ),
        f"| Better shadow count | {int(summary.get('better_shadow_count', 0))} |",
        f"| Shadow improvement candidates | {int(summary.get('shadow_improvement_candidates', 0))} |",
        f"| Worse shadow count | {int(summary.get('worse_shadow_count', 0))} |",
        f"| Unsafe shadow count | {int(summary.get('unsafe_shadow_count', 0))} |",
        "",
        "## Mismatch By Group",
        "",
        "| Group | Mismatches |",
        "| --- | ---: |",
    ]
    mismatch_by_group = _mapping(report.get("mismatch_by_group"))
    if mismatch_by_group:
        for group, count in mismatch_by_group.items():
            lines.append(f"| `{_escape_table(group)}` | {int(count)} |")
    else:
        lines.append("| `none` | 0 |")
    lines += [
        "",
        "## Top Unsafe Examples",
        "",
    ]
    unsafe_examples = list(report.get("top_unsafe_examples") or [])
    if unsafe_examples:
        lines += ["| Case | Group | Shadow | Reason | Trace |", "| --- | --- | --- | --- | --- |"]
        for item in unsafe_examples:
            item_map = _mapping(item)
            lines.append(
                f"| `{_escape_table(item_map.get('case_id') or '')}` | "
                f"`{_escape_table(item_map.get('group') or 'unknown')}` | "
                f"`{_escape_table(item_map.get('shadow') or '')}` | "
                f"{_escape_table(item_map.get('reason') or '')} | "
                f"`{_escape_table(item_map.get('trace_id') or '')}` |"
            )
    else:
        lines.append("No unsafe shadow examples.")
    lines += [
        "",
        "## Top Possible Improvements",
        "",
    ]
    improvements = list(report.get("top_possible_improvements") or [])
    if improvements:
        lines += [
            "| Case | Group | Deterministic | Shadow | Delta | Trace |",
            "| --- | --- | --- | --- | ---: | --- |",
        ]
        for item in improvements:
            item_map = _mapping(item)
            lines.append(
                f"| `{_escape_table(item_map.get('case_id') or '')}` | "
                f"`{_escape_table(item_map.get('group') or 'unknown')}` | "
                f"`{_escape_table(item_map.get('deterministic') or '')}` | "
                f"`{_escape_table(item_map.get('shadow') or '')}` | "
                f"{float(item_map.get('quality_delta') or 0):.4f} | "
                f"`{_escape_table(item_map.get('trace_id') or '')}` |"
            )
    else:
        lines.append("No safe possible improvements.")
    lines += [
        "",
        "## Top 20 Mismatches",
        "",
    ]
    mismatches = list(report.get("top_20_mismatches") or [])
    if not mismatches:
        lines.append("No mismatches.")
        return "\n".join(lines) + "\n"
    lines += [
        "| Case | Group | Deterministic | Shadow | Trace |",
        "| --- | --- | --- | --- | --- |",
    ]
    for mismatch in mismatches:
        item = _mapping(mismatch)
        lines.append(
            f"| `{_escape_table(item.get('case_id') or '')}` | "
            f"`{_escape_table(item.get('group') or 'unknown')}` | "
            f"`{_escape_table(item.get('deterministic') or '')}` | "
            f"`{_escape_table(item.get('shadow') or '')}` | "
            f"`{_escape_table(item.get('trace_id') or '')}` |"
        )
    return "\n".join(lines) + "\n"


def render_generated_issue_index_markdown(
    *,
    individual_scores: Sequence[CaseQualityScore],
    p2_scores: Sequence[CaseQualityScore],
) -> str:
    lines = [
        "# Generated Pipi Improvement Issues",
        "",
        "This directory is generated from benchmark quality reports.",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Individual P0/P1 issues | {len(individual_scores)} |",
        f"| Aggregated P2 cases | {len(p2_scores)} |",
        "",
    ]
    if not individual_scores:
        lines.append("No P0/P1 issues generated.")
        lines.append("")
    else:
        lines += [
            "## Individual Issues",
            "",
            "| File | Priority | Owner | Bucket | Case | Score | Primary Issues |",
            "| --- | --- | --- | --- | --- | ---: | --- |",
        ]
        for index, score in enumerate(
            sorted(
                individual_scores,
                key=lambda item: (
                    _priority_rank(_issue_priority(item)),
                    _issue_owner(item),
                    item.quality_score,
                    item.case_id,
                ),
            )
        ):
            lines.append(
                f"| `issuer_{index:03d}.md` | `{_issue_priority(score)}` | "
                f"`{_issue_owner(score)}` | `{_issue_bucket(score)}` | "
                f"`{_escape_table(score.case_id)}` | {score.quality_score:.4f} | "
                f"{_issue_text(score)} |"
            )
        lines.append("")
    lines += [
        "## P2 Aggregate",
        "",
        "See `p2_aggregate.md` for lower-priority degraded cases.",
        "",
    ]
    return "\n".join(lines)


def render_generated_issue_markdown(score: CaseQualityScore, *, index: int) -> str:
    priority = _issue_priority(score)
    owner = _issue_owner(score)
    bucket = _issue_bucket(score)
    message = str(score.metadata.get("message") or "")
    trace_id = str(score.metadata.get("trace_id") or "")
    agent_run_id = str(score.metadata.get("agent_run_id") or "")
    retrieval_run_id = str(score.metadata.get("retrieval_run_id") or "")
    admin_trace_api_path = f"/admin/api/traces/{agent_run_id or trace_id}" if (agent_run_id or trace_id) else ""
    title = _generated_issue_title(score)
    lines = [
        f"# issuer_{index:03d}.md",
        "",
        "## 失败结论",
        "",
        f"{priority} / `{owner}` / `{bucket}`：{title}",
        "",
        "## 失败 Case",
        "",
        f"- case_id: `{score.case_id}`",
        f"- message: {message or '-'}",
        f"- expected_kind: `{score.expected_kind}`",
        f"- actual_kind: `{score.actual_kind}`",
        f"- quality_score: `{score.quality_score:.4f}`",
        f"- status: `{score.status}`",
        f"- trace_id: `{trace_id or '-'}`",
        f"- agent_run_id: `{agent_run_id or '-'}`",
        f"- retrieval_run_id: `{retrieval_run_id or '-'}`",
        f"- admin_trace_api_path: `{admin_trace_api_path or '-'}`",
        "",
        "## 失败证据",
        "",
        "| Issue | Severity | Penalty | Dimension | Message |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for issue in score.issues:
        lines.append(
            f"| `{issue.code}` | `{issue.severity}` | {issue.penalty:.2f} | "
            f"`{_generated_issue_dimension(issue.code)}` | {_escape_table(issue.message or '-')} |"
        )
    lines += [
        "",
        "## 复现方式",
        "",
        "1. 运行对应 benchmark case，或在本地用 `/v1/chat/turn` 发送上面的 message。",
        "2. 打开 Admin Trace，按 `agent_run_id` 或 `trace_id` 检查 InputGate、ContextBuilder、PipiLoop、AbilityCenter、Evaluator、AnswerGate。",
        "3. 对照本 issue 的 issue code 和 quality dimension 修复。",
        "",
        "## 修复范围",
        "",
        _fix_scope_text(score),
        "",
        "## 禁止修改",
        "",
        "- 不要改 iOS 前端或 Claude Design 原型。",
        "- 不要用 smoke/eval bypass 掩盖 product path。",
        "- 不要让模型直接吐推荐卡 JSON。",
        "- 不要绕过 AbilityCenter 创建推荐卡或求助卡。",
        "- 不要删除或放宽质量评分测试。",
        "",
        "## 建议测试",
        "",
    ]
    for test in _suggested_tests(score):
        lines.append(f"- `{test}`")
    lines += [
        "",
        "## 验收标准",
        "",
        "- 该 case 不再出现在 P0/P1 generated issue 中。",
        "- `quality_score` 高于当前分数，且对应 issue code 消失。",
        "- `uv run pytest -q -rx` 通过。",
        "- `uv run ruff check app tests` 通过。",
        "",
    ]
    return "\n".join(lines)


def render_p2_aggregate_markdown(scores: Sequence[CaseQualityScore]) -> str:
    lines = [
        "# P2 Aggregate Cases",
        "",
        "P2 cases are lower-priority degradations. They are grouped here to avoid noisy per-case tickets.",
        "",
    ]
    if not scores:
        lines.append("No P2 cases.")
        return "\n".join(lines) + "\n"
    issue_counts = Counter(issue.code for score in scores for issue in score.issues)
    owner_counts = Counter(_issue_owner(score) for score in scores)
    lines += [
        "## Summary",
        "",
        "| Owner | Cases |",
        "| --- | ---: |",
    ]
    for owner, count in sorted(owner_counts.items()):
        lines.append(f"| `{owner}` | {count} |")
    lines += [
        "",
        "## Top Issues",
        "",
        "| Issue | Count |",
        "| --- | ---: |",
    ]
    for code, count in issue_counts.most_common(20):
        lines.append(f"| `{code}` | {count} |")
    lines += [
        "",
        "## Cases",
        "",
        "| Case | Owner | Score | Actual | Issues |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for score in sorted(scores, key=lambda item: (item.quality_score, item.case_id)):
        lines.append(
            f"| `{_escape_table(score.case_id)}` | `{_issue_owner(score)}` | "
            f"{score.quality_score:.4f} | `{score.actual_kind}` | {_issue_text(score)} |"
        )
    return "\n".join(lines) + "\n"


def _issue_bucket(score: CaseQualityScore) -> str:
    if is_seed_gap_case(score):
        return "seed_gap"
    if is_agent_improvement_case(score):
        return "agent_improvement"
    return "passed"


def _issue_priority(score: CaseQualityScore) -> str:
    codes = {issue.code for issue in score.issues}
    if codes & _P0_ISSUE_CODES:
        return "P0"
    if is_seed_gap_case(score):
        return "P1"
    if score.errors:
        return "P1"
    if score.status != "passed":
        return "P2"
    return "P2"


def _priority_rank(priority: str) -> int:
    return {"P0": 0, "P1": 1, "P2": 2}.get(priority, 9)


def _issue_owner(score: CaseQualityScore) -> str:
    if is_seed_gap_case(score):
        return "data_seed"
    codes = {issue.code for issue in score.issues}
    if codes & {
        "response_kind_mismatch",
        "location_state_mismatch",
        "target_type_mismatch",
    } or any(code.startswith("venue_order_") for code in codes):
        return "router"
    if any(code.startswith("tool_call_") for code in codes):
        return "tool"
    if "retrieval_run_missing" in codes or any("evidence" in code or "image" in code for code in codes):
        return "evidence"
    if any(code.startswith("help_card_") for code in codes):
        return "help_card"
    if any(code.startswith("recommendation_card_") for code in codes):
        return "card_contract"
    if "agent_run_id_missing" in codes or "response_missing" in codes:
        return "runtime"
    return "agent"


def _generated_issue_title(score: CaseQualityScore) -> str:
    if is_seed_gap_case(score):
        return "期望推荐卡但实际生成求助卡，需要补 seed/approved answer。"
    owner = _issue_owner(score)
    if owner == "router":
        return "顶层路由或 target/location 判定错误。"
    if owner == "evidence":
        return "证据链不足或证据字段缺失。"
    if owner == "tool":
        return "工具调用缺失或工具名不符合预期。"
    if owner == "help_card":
        return "求助卡结构或具体性不足。"
    if owner == "card_contract":
        return "推荐卡契约或内容质量不合格。"
    if owner == "runtime":
        return "运行时响应或持久化信息缺失。"
    return "Agent 行为需要改进。"


def _fix_scope_text(score: CaseQualityScore) -> str:
    owner = _issue_owner(score)
    if owner == "data_seed":
        return "只补本地 seed、IntentAnswer、approved answer 或可检索数据；不要修改 router/evaluator 来掩盖数据缺口。"
    if owner == "router":
        return "修改 InputGate、query rewrite、intent router 或 deterministic matcher；不要改推荐卡 schema。"
    if owner == "evidence":
        return "修改 retrieval/evidence evaluator/provenance 写入；不要把 POI 当成好吃证据。"
    if owner == "tool":
        return "修改 AbilityCenter/tool schema/tool result 回灌；不要绕过 tool 直接写卡。"
    if owner == "help_card":
        return "修改 draft/update help card 的结构化槽位和质量 gate；不要恢复泛求助卡兜底。"
    if owner == "card_contract":
        return "修改 recommendation card tool/evaluator/serializer；不要返回 legacy reasons/bullets/followups。"
    if owner == "runtime":
        return "修改 `/v1/chat/turn` product path、trace 或 metadata 持久化；不要启用 smoke bypass。"
    return "修改 Agent harness 中对应 owner 的最小范围，并补回归测试。"


def _suggested_tests(score: CaseQualityScore) -> list[str]:
    owner = _issue_owner(score)
    if owner == "router":
        return [
            "app/tests/test_top_level_intent_router.py",
            "app/tests/test_input_gate_slot_extraction.py",
            "app/tests/test_onsite_report_regressions.py",
        ]
    if owner == "data_seed":
        return [
            "app/tests/test_quality_report_generation.py",
            "app/tests/test_onsite_report_regressions.py",
        ]
    if owner == "evidence":
        return [
            "app/tests/test_evidence_evaluator_quality_gate.py",
            "app/tests/test_decision_factor_not_generic.py",
        ]
    if owner == "tool":
        return [
            "app/tests/test_ability_center_happy_path.py",
            "app/tests/test_product_path_trace_persistence.py",
        ]
    if owner == "help_card":
        return [
            "app/tests/test_help_card_quality_gate.py",
            "app/tests/test_clarification_not_help_card.py",
        ]
    if owner == "card_contract":
        return [
            "app/tests/test_recommendation_card_v2_contract.py",
            "app/tests/test_card_contract_and_answer_gate.py",
        ]
    return [
        "app/tests/test_product_path_trace_persistence.py",
        "app/tests/test_eval_smoke_bypass_guardrails.py",
    ]


def _generated_issue_dimension(code: str) -> str:
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


def generate_quality_reports_from_files(
    *,
    results_path: str | Path,
    output_dir: str | Path,
    benchmark_path: str | Path | None = None,
    low_quality_threshold: float = DEFAULT_LOW_QUALITY_THRESHOLD,
) -> dict[str, Path]:
    rows = load_json_or_jsonl(results_path)
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise ValueError("Results file must be a JSON array or JSONL rows.")
    mapping_rows = [dict(row) for row in rows if isinstance(row, Mapping)]
    if not mapping_rows:
        raise ValueError("results file contains zero evaluated cases")
    benchmark_cases = load_benchmark_cases(benchmark_path) if benchmark_path else []
    return write_quality_reports(
        mapping_rows,
        output_dir,
        benchmark_cases=benchmark_cases,
        low_quality_threshold=low_quality_threshold,
        report_mode="evaluated",
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write pipi benchmark quality reports.")
    parser.add_argument("--results", help="Benchmark result JSON or JSONL file.")
    parser.add_argument("--benchmark", help="Benchmark suite JSON/JSONL file for coverage.")
    parser.add_argument("--out", default="benchmarks/reports/latest", help="Report output dir.")
    parser.add_argument(
        "--low-quality-threshold",
        type=float,
        default=DEFAULT_LOW_QUALITY_THRESHOLD,
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not args.results:
        if not args.benchmark:
            parser.error("--benchmark is required when --results is omitted")
        paths = write_quality_reports(
            [],
            args.out,
            benchmark_cases=load_benchmark_cases(args.benchmark),
            low_quality_threshold=args.low_quality_threshold,
            report_mode="coverage_only",
        )
        for name, path in paths.items():
            print(f"{name}: {path}")
        return 0
    try:
        paths = generate_quality_reports_from_files(
            results_path=args.results,
            output_dir=args.out,
            benchmark_path=args.benchmark,
            low_quality_threshold=args.low_quality_threshold,
        )
    except ValueError as exc:
        print(str(exc))
        return 2
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return text or "unknown"


def _pct(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value * 100:.2f}%"
    return "0.00%"


def is_seed_gap_case(score: CaseQualityScore) -> bool:
    return score.expected_kind == "recommendation_card" and score.actual_kind == "help_card_draft"


def is_agent_improvement_case(score: CaseQualityScore) -> bool:
    if is_seed_gap_case(score):
        return False
    return score.status != "passed"


def _expected_distribution(cases: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    for case in cases:
        suite_distribution = _mapping(case.get("expected_distribution"))
        if suite_distribution:
            return _normalize_distribution(suite_distribution)
    return DEFAULT_BENCHMARK_DISTRIBUTION if len(cases) == 500 else {}


def _distribution_errors(
    actual: Mapping[str, Mapping[str, int]],
    expected: Mapping[str, Mapping[str, int]],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if not expected:
        return errors
    for section, expected_values in expected.items():
        actual_values = actual.get(section) or {}
        for value, expected_count in expected_values.items():
            actual_count = int(actual_values.get(value, 0))
            if actual_count != expected_count:
                errors.append(
                    {
                        "bucket": f"{section}.{value}",
                        "expected": expected_count,
                        "actual": actual_count,
                    }
                )
        unexpected_values = set(actual_values) - set(expected_values)
        for value in sorted(unexpected_values):
            errors.append(
                {
                    "bucket": f"{section}.{value}",
                    "expected": 0,
                    "actual": int(actual_values[value]),
                }
            )
    return errors


def _normalize_distribution(value: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    normalized: dict[str, dict[str, int]] = {}
    for section, counts in value.items():
        if isinstance(counts, Mapping):
            normalized[str(section)] = {
                str(name): int(count)
                for name, count in counts.items()
                if isinstance(count, (int, float))
            }
    return normalized


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dumped
    return {}


def _shadow_decision_from_row(row: Mapping[str, Any]) -> dict[str, Any] | None:
    case = _report_case(row)
    response = _report_response(row)
    output_json = _report_output_json(row, response)
    shadow = _extract_shadow_payload(row, response, output_json)
    if shadow is None:
        return None

    summary = _mapping(shadow.get("summary"))
    result = _mapping(shadow.get("result"))
    deterministic = _deterministic_shadow_label(row, response, output_json, summary, result)
    shadow_label = _shadow_result_label(summary, result)
    timeout = _shadow_timeout(summary, result)
    provider_error = _shadow_provider_error(summary, result, timeout=timeout)
    schema_error = _shadow_schema_error(
        summary,
        result,
        provider_error=provider_error,
        timeout=timeout,
    )
    schema_valid = _shadow_schema_valid(
        summary,
        result,
        shadow_label=shadow_label,
        schema_error=schema_error,
        provider_error=provider_error,
        timeout=timeout,
    )
    mismatch = _shadow_mismatch(
        summary,
        result,
        deterministic=deterministic,
        shadow=shadow_label,
        schema_valid=schema_valid,
        schema_error=schema_error,
        provider_error=provider_error,
        timeout=timeout,
    )

    return {
        "case_id": _report_case_id(case, row, response, output_json),
        "group": _report_group(case, row, response, output_json),
        "deterministic": deterministic,
        "shadow": shadow_label,
        "shadow_payload": result,
        "mismatch": mismatch,
        "quality_delta_estimate": None,
        "trace_id": _report_trace_id(row, response, output_json, summary, result),
        "shadow_enabled": _shadow_enabled(summary, result),
        "schema_valid": schema_valid,
        "schema_error": schema_error,
        "provider_error": provider_error,
        "timeout": timeout,
    }


def _enrich_shadow_decision(decision: Mapping[str, Any]) -> dict[str, Any]:
    enriched = dict(decision)
    enriched.update(score_shadow_decision(enriched))
    return enriched


def _shadow_decision_jsonl_payload(decision: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "case_id": decision.get("case_id"),
        "deterministic": decision.get("deterministic"),
        "shadow": decision.get("shadow"),
        "mismatch": bool(decision.get("mismatch")),
        "deterministic_quality": decision.get("deterministic_quality"),
        "shadow_predicted_quality": decision.get("shadow_predicted_quality"),
        "quality_delta": decision.get("quality_delta"),
        "quality_delta_estimate": decision.get("quality_delta_estimate"),
        "mismatch_reason": decision.get("mismatch_reason"),
        "should_promote_shadow": bool(decision.get("should_promote_shadow")),
        "unsafe_to_promote_reason": decision.get("unsafe_to_promote_reason"),
        "trace_id": decision.get("trace_id"),
    }


def _extract_shadow_payload(
    row: Mapping[str, Any],
    response: Mapping[str, Any],
    output_json: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]] | None:
    candidates: list[dict[str, Mapping[str, Any]]] = []
    for container in _shadow_containers(row, response, output_json):
        _append_shadow_candidate(candidates, container)
    if not candidates:
        return None

    summary: dict[str, Any] = {}
    result: dict[str, Any] = {}
    for candidate in candidates:
        summary.update(dict(candidate.get("summary") or {}))
        result.update(dict(candidate.get("result") or {}))
    return {"summary": summary, "result": result}


def _shadow_containers(
    row: Mapping[str, Any],
    response: Mapping[str, Any],
    output_json: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    containers: list[Mapping[str, Any]] = [
        row,
        response,
        _mapping(response.get("metadata")),
        output_json,
        _mapping(output_json.get("metadata")),
    ]
    for event in _loop_trace_values(row, response, output_json):
        event_map = _mapping(event)
        if not event_map:
            continue
        containers.append(event_map)
        for key in ("payload", "data", "output", "result"):
            nested = _mapping(event_map.get(key))
            if nested:
                containers.append(nested)
    return containers


def _append_shadow_candidate(
    candidates: list[dict[str, Mapping[str, Any]]],
    container: Mapping[str, Any],
) -> None:
    if not container:
        return
    summary = dict(_mapping(container.get("shadow_summary")))
    result = dict(_mapping(container.get("shadow_reasoner_result")))

    for nested_key in ("shadow_llm", "shadow"):
        nested = _mapping(container.get(nested_key))
        if not nested:
            continue
        nested_summary = (
            _mapping(nested.get("summary"))
            or _mapping(nested.get("shadow_summary"))
            or _mapping(nested.get("comparison"))
        )
        nested_result = (
            _mapping(nested.get("reasoner_result"))
            or _mapping(nested.get("shadow_reasoner_result"))
            or _mapping(nested.get("result"))
            or _mapping(nested.get("decision"))
        )
        summary.update(dict(nested_summary))
        result.update(dict(nested_result))
        if not nested_summary and not nested_result and _looks_like_shadow_payload(nested):
            summary.update(dict(nested))

    if summary or result:
        candidates.append({"summary": summary, "result": result})


def _looks_like_shadow_payload(value: Mapping[str, Any]) -> bool:
    return any(
        key in value
        for key in (
            "enabled",
            "schema_valid",
            "schema_error",
            "provider_error",
            "timeout",
            "mismatch",
            "deterministic",
            "shadow",
            "decision",
        )
    )


def _report_case(row: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(row.get("case")) or _mapping(row.get("benchmark_case")) or {}


def _report_response(row: Mapping[str, Any]) -> Mapping[str, Any]:
    response = (
        _mapping(row.get("response"))
        or _mapping(row.get("actual_response"))
        or _mapping(row.get("actual"))
        or _mapping(row.get("backend_response"))
        or _mapping(row.get("response_body"))
        or _mapping(row.get("body"))
        or _mapping(row.get("result"))
    )
    if response:
        return response
    return row if _looks_like_report_response(row) else {}


def _report_output_json(
    row: Mapping[str, Any],
    response: Mapping[str, Any],
) -> Mapping[str, Any]:
    agent_run = _mapping(row.get("agent_run"))
    return (
        _mapping(row.get("output_json"))
        or _mapping(response.get("output_json"))
        or _mapping(agent_run.get("output_json"))
        or {}
    )


def _looks_like_report_response(value: Mapping[str, Any]) -> bool:
    return any(
        key in value
        for key in (
            "response_kind",
            "ui_events",
            "data",
            "cards",
            "help_cards",
            "assistant_message",
            "tool_calls",
        )
    )


def _report_case_id(
    case: Mapping[str, Any],
    row: Mapping[str, Any],
    response: Mapping[str, Any],
    output_json: Mapping[str, Any],
) -> str:
    response_metadata = _mapping(response.get("metadata"))
    output_metadata = _mapping(output_json.get("metadata"))
    return (
        _first_text(
            case.get("id"),
            case.get("case_id"),
            row.get("case_id"),
            row.get("id"),
            response_metadata.get("benchmark_case_id"),
            output_metadata.get("benchmark_case_id"),
        )
        or "unknown_case"
    )


def _report_group(
    case: Mapping[str, Any],
    row: Mapping[str, Any],
    response: Mapping[str, Any],
    output_json: Mapping[str, Any],
) -> str:
    response_metadata = _mapping(response.get("metadata"))
    output_metadata = _mapping(output_json.get("metadata"))
    return (
        _first_text(
            case.get("category"),
            case.get("group"),
            row.get("category"),
            row.get("group"),
            response_metadata.get("benchmark_group"),
            response_metadata.get("group"),
            output_metadata.get("benchmark_group"),
            output_metadata.get("group"),
        )
        or "unknown"
    )


def _report_trace_id(
    row: Mapping[str, Any],
    response: Mapping[str, Any],
    output_json: Mapping[str, Any],
    summary: Mapping[str, Any],
    result: Mapping[str, Any],
) -> str | None:
    response_metadata = _mapping(response.get("metadata"))
    output_metadata = _mapping(output_json.get("metadata"))
    return _first_text(
        summary.get("trace_id"),
        result.get("trace_id"),
        row.get("trace_id"),
        row.get("agent_run_id"),
        response.get("trace_id"),
        response_metadata.get("trace_id"),
        response_metadata.get("agent_run_id"),
        output_json.get("trace_id"),
        output_json.get("agent_run_id"),
        output_metadata.get("trace_id"),
        output_metadata.get("agent_run_id"),
    ) or None


def _deterministic_shadow_label(
    row: Mapping[str, Any],
    response: Mapping[str, Any],
    output_json: Mapping[str, Any],
    summary: Mapping[str, Any],
    result: Mapping[str, Any],
) -> str | None:
    for value in (
        summary.get("deterministic"),
        summary.get("deterministic_decision"),
        summary.get("deterministic_reasoner_result"),
        summary.get("baseline"),
        summary.get("actual"),
        result.get("deterministic"),
        result.get("deterministic_decision"),
    ):
        label = _decision_label(value)
        if label:
            return label

    for candidate in (
        _response_decision_label(response),
        _response_decision_label(output_json),
        _loop_trace_decision_label(row, response, output_json),
    ):
        if candidate:
            return candidate
    return None


def _shadow_result_label(summary: Mapping[str, Any], result: Mapping[str, Any]) -> str | None:
    for value in (
        summary.get("shadow"),
        summary.get("shadow_decision"),
        summary.get("llm_decision"),
        summary.get("shadow_reasoner_result"),
        result.get("shadow"),
        result.get("shadow_decision"),
        result,
    ):
        label = _decision_label(value)
        if label:
            return label
    return None


def _decision_label(value: Any, *, _depth: int = 0) -> str | None:
    if _depth > 4 or value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    mapped = _mapping(value)
    if not mapped:
        return None

    for key in (
        "decision",
        "reasoner_result",
        "result",
        "output",
        "parsed",
        "validated",
        "shadow_reasoner_result",
    ):
        nested = mapped.get(key)
        if nested is value:
            continue
        label = _decision_label(nested, _depth=_depth + 1)
        if label:
            return label

    tool_call = _mapping(mapped.get("tool_call")) or _mapping(mapped.get("function_call"))
    decision_type = _first_text(
        mapped.get("type"),
        mapped.get("decision_type"),
        mapped.get("kind"),
        tool_call.get("type"),
    )
    tool_name = _first_text(
        mapped.get("tool_name"),
        mapped.get("function_name"),
        mapped.get("name"),
        mapped.get("tool"),
        tool_call.get("tool_name"),
        tool_call.get("name"),
        tool_call.get("function_name"),
    )
    if decision_type in {"tool", "tool_call", "function", "function_call"}:
        return f"tool:{tool_name}" if tool_name else "tool"
    if tool_name and not _response_kind_from_mapping(mapped):
        return f"tool:{tool_name}"

    response_kind = _response_kind_from_mapping(mapped)
    if decision_type in {"answer", "assistant_answer", "final_answer"}:
        return f"answer:{response_kind}" if response_kind else "answer"
    if response_kind:
        return f"answer:{response_kind}"
    return None


def _response_decision_label(response: Mapping[str, Any]) -> str | None:
    tool_names = _tool_names_from_mapping(response)
    for preferred in (
        "create_recommendation_card",
        "draft_help_card",
        "update_help_card",
        "save_intent_answer",
        "emit_light_event",
    ):
        if preferred in tool_names:
            return f"tool:{preferred}"
    if tool_names:
        return f"tool:{sorted(tool_names)[0]}"
    response_kind = _response_kind_from_mapping(response)
    return f"answer:{response_kind}" if response_kind else None


def _loop_trace_decision_label(
    row: Mapping[str, Any],
    response: Mapping[str, Any],
    output_json: Mapping[str, Any],
) -> str | None:
    for event in reversed(_loop_trace_values(row, response, output_json)):
        event_map = _mapping(event)
        event_name = _first_text(
            event_map.get("event"),
            event_map.get("name"),
            event_map.get("type"),
            event_map.get("stage"),
        )
        if event_name not in {"reasoner_decision", "deterministic_reasoner_result"}:
            continue
        for key in ("data", "payload", "decision", "result"):
            label = _decision_label(event_map.get(key))
            if label:
                return label
    return None


def _loop_trace_values(
    row: Mapping[str, Any],
    response: Mapping[str, Any],
    output_json: Mapping[str, Any],
) -> list[Any]:
    response_metadata = _mapping(response.get("metadata"))
    output_metadata = _mapping(output_json.get("metadata"))
    values: list[Any] = []
    for candidate in (
        row.get("loop_trace"),
        response.get("loop_trace"),
        response_metadata.get("loop_trace"),
        output_json.get("loop_trace"),
        output_metadata.get("loop_trace"),
    ):
        values.extend(_sequence(candidate))
    return values


def _response_kind_from_mapping(value: Mapping[str, Any]) -> str | None:
    explicit = _first_text(value.get("response_kind"), value.get("actual_kind"))
    if explicit:
        return explicit
    data = _mapping(value.get("data"))
    if _mapping(data.get("recommendation_card")):
        return "recommendation_card"
    if _mapping(data.get("help_card")):
        return "help_card_draft"
    if _mapping(data.get("clarification")):
        return "clarification"
    for event in _sequence(value.get("ui_events")):
        event_type = _first_text(_mapping(event).get("type"))
        if event_type == "show_recommendation_card":
            return "recommendation_card"
        if event_type == "show_help_card_draft":
            return "help_card_draft"
    return None


def _tool_names_from_mapping(value: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()
    for call in _sequence(value.get("tool_calls")):
        call_map = _mapping(call)
        name = _first_text(call_map.get("name"), call_map.get("tool_name"))
        if name:
            names.add(name)
    metadata = _mapping(value.get("metadata"))
    selected_tool = _first_text(metadata.get("selected_tool"), value.get("selected_tool"))
    if selected_tool:
        names.add(selected_tool)
    for result in _sequence(value.get("tool_results")):
        result_map = _mapping(result)
        decision = _mapping(result_map.get("decision"))
        name = _first_text(
            decision.get("tool_name"),
            result_map.get("tool_name"),
            _mapping(result_map.get("tool_result")).get("tool_name"),
        )
        if name:
            names.add(name)
    return names


def _shadow_enabled(summary: Mapping[str, Any], result: Mapping[str, Any]) -> bool:
    explicit = _first_bool(summary.get("enabled"), result.get("enabled"))
    if explicit is not None:
        return explicit
    status = _shadow_status(summary, result)
    if status in {"disabled", "skipped", "sampled_out"}:
        return False
    return bool(summary or result)


def _shadow_schema_valid(
    summary: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    shadow_label: str | None,
    schema_error: bool,
    provider_error: bool,
    timeout: bool,
) -> bool:
    explicit = _first_bool(
        summary.get("schema_valid"),
        result.get("schema_valid"),
        summary.get("valid"),
        result.get("valid"),
    )
    if explicit is not None:
        return explicit and not schema_error and not provider_error and not timeout
    return bool(shadow_label and not schema_error and not provider_error and not timeout)


def _shadow_schema_error(
    summary: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    provider_error: bool,
    timeout: bool,
) -> bool:
    if _first_bool(summary.get("schema_error"), result.get("schema_error")) is True:
        return True
    status = _shadow_status(summary, result)
    error_type = _shadow_error_type(summary, result)
    if "schema" in status or "validation" in status:
        return True
    if "schema" in error_type or "validation" in error_type:
        return True
    explicit_valid = _first_bool(
        summary.get("schema_valid"),
        result.get("schema_valid"),
        summary.get("valid"),
        result.get("valid"),
    )
    return explicit_valid is False and not provider_error and not timeout


def _shadow_provider_error(
    summary: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    timeout: bool,
) -> bool:
    if _first_bool(summary.get("provider_error"), result.get("provider_error")) is True:
        return True
    status = _shadow_status(summary, result)
    error_type = _shadow_error_type(summary, result)
    if "provider" in status or "provider" in error_type:
        return True
    if "api_error" in status or "api_error" in error_type:
        return True
    if status in {"error", "failed"} and not timeout:
        return True
    return False


def _shadow_timeout(summary: Mapping[str, Any], result: Mapping[str, Any]) -> bool:
    if _first_bool(
        summary.get("timeout"),
        result.get("timeout"),
        summary.get("timed_out"),
        result.get("timed_out"),
    ) is True:
        return True
    status = _shadow_status(summary, result)
    error_type = _shadow_error_type(summary, result)
    return "timeout" in status or "timed_out" in status or "timeout" in error_type


def _shadow_mismatch(
    summary: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    deterministic: str | None,
    shadow: str | None,
    schema_valid: bool,
    schema_error: bool,
    provider_error: bool,
    timeout: bool,
) -> bool:
    explicit = _first_bool(
        summary.get("mismatch"),
        result.get("mismatch"),
        summary.get("deterministic_shadow_mismatch"),
    )
    if explicit is not None:
        return explicit
    if schema_error or provider_error or timeout or not schema_valid:
        return False
    return bool(deterministic and shadow and deterministic != shadow)


def _shadow_status(summary: Mapping[str, Any], result: Mapping[str, Any]) -> str:
    return _first_text(
        summary.get("status"),
        result.get("status"),
        summary.get("state"),
        result.get("state"),
    ).lower()


def _shadow_error_type(summary: Mapping[str, Any], result: Mapping[str, Any]) -> str:
    return _first_text(
        summary.get("error_type"),
        result.get("error_type"),
        summary.get("error_code"),
        result.get("error_code"),
        _mapping(summary.get("error")).get("type"),
        _mapping(result.get("error")).get("type"),
    ).lower()


def _first_bool(*values: Any) -> bool | None:
    for value in values:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            text = value.strip().lower()
            if text in {"true", "1", "yes", "y"}:
                return True
            if text in {"false", "0", "no", "n"}:
                return False
    return None


def _sequence(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _issue_text(score: CaseQualityScore) -> str:
    return ", ".join(f"`{issue.code}`" for issue in score.issues) or "-"


def _escape_table(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _score_payload(score: CaseQualityScore) -> dict[str, Any]:
    payload = score.to_dict()
    if is_seed_gap_case(score):
        payload["report_bucket"] = "seed_gap"
    elif is_agent_improvement_case(score):
        payload["report_bucket"] = "agent_improvement"
    else:
        payload["report_bucket"] = "passed"
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
