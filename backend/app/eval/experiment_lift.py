"""Experiment lift reporting for benchmark/effect rows."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.eval.quality_scoring import score_case_result


ACCEPT_EVENT_TYPES = {
    "card_accepted",
    "recommendation_card_accepted",
    "final_recommendation_accepted",
}


def build_experiment_lift_report(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, dict[str, list[Mapping[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    unassigned = 0
    for row in rows:
        assignments = _variant_ids(row)
        if not assignments:
            unassigned += 1
            continue
        for experiment_id, variant_id in assignments.items():
            buckets[experiment_id][variant_id].append(row)

    experiments: dict[str, Any] = {}
    for experiment_id, variants in sorted(buckets.items()):
        variant_summaries = {
            variant_id: _summarize_variant(variant_rows)
            for variant_id, variant_rows in sorted(variants.items())
        }
        baseline_variant = "control" if "control" in variant_summaries else next(iter(variant_summaries), None)
        experiments[experiment_id] = {
            "baseline_variant": baseline_variant,
            "variants": variant_summaries,
            "deltas": _variant_deltas(variant_summaries, baseline_variant=baseline_variant),
        }

    return {
        "summary": {
            "total_rows": len(rows),
            "assigned_rows": len(rows) - unassigned,
            "unassigned_rows": unassigned,
            "experiment_count": len(experiments),
        },
        "experiments": experiments,
        "metadata": {"version": "experiment_lift_v1"},
    }


def write_experiment_lift_reports(rows: Sequence[Mapping[str, Any]], output_dir: str | Path) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    report = build_experiment_lift_report(rows)
    paths = {
        "experiment_lift_json": output / "experiment_lift_report.json",
        "experiment_lift_markdown": output / "experiment_lift_report.md",
    }
    paths["experiment_lift_json"].write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    paths["experiment_lift_markdown"].write_text(render_experiment_lift_markdown(report), encoding="utf-8")
    return paths


def render_experiment_lift_markdown(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    lines = [
        "# Experiment Lift Report",
        "",
        f"- Total rows: `{summary.get('total_rows', 0)}`",
        f"- Assigned rows: `{summary.get('assigned_rows', 0)}`",
        f"- Unassigned rows: `{summary.get('unassigned_rows', 0)}`",
        f"- Experiments: `{summary.get('experiment_count', 0)}`",
        "",
    ]
    experiments = _mapping(report.get("experiments"))
    if not experiments:
        lines.append("No experiment assignments found in result rows.")
        return "\n".join(lines) + "\n"
    for experiment_id, experiment in sorted(experiments.items()):
        payload = _mapping(experiment)
        lines += [
            f"## `{experiment_id}`",
            "",
            f"- Baseline: `{payload.get('baseline_variant')}`",
            "",
            "| Variant | Cases | Pass Rate | Variant Quality | Accept Rate | Δ Pass | Δ Quality |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        variants = _mapping(payload.get("variants"))
        deltas = _mapping(payload.get("deltas"))
        for variant_id, variant in sorted(variants.items()):
            item = _mapping(variant)
            delta = _mapping(deltas.get(variant_id))
            lines.append(
                f"| `{variant_id}` | {item.get('case_count', 0)} | "
                f"{item.get('pass_rate', 0):.3f} | {item.get('variant_quality', item.get('average_quality', 0)):.3f} | "
                f"{item.get('accept_rate', 0):.3f} | {delta.get('pass_rate_delta', 0):.3f} | "
                f"{delta.get('variant_quality_delta', delta.get('average_quality_delta', 0)):.3f} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _summarize_variant(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    scores = [score_case_result(row) for row in rows]
    accepted = sum(1 for row in rows if _is_accepted(row))
    passed = sum(1 for score in scores if score.passed)
    total = len(rows)
    return {
        "case_count": total,
        "passed_count": passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "average_quality": round(sum(score.quality_score for score in scores) / total, 4) if total else 0.0,
        "variant_quality": round(sum(score.quality_score for score in scores) / total, 4) if total else 0.0,
        "accepted_count": accepted,
        "accept_rate": round(accepted / total, 4) if total else 0.0,
        "case_ids": [str(row.get("case_id") or row.get("id") or "") for row in rows[:20]],
    }


def _variant_deltas(
    variants: Mapping[str, Mapping[str, Any]],
    *,
    baseline_variant: str | None,
) -> dict[str, Any]:
    if not baseline_variant or baseline_variant not in variants:
        return {}
    baseline = _mapping(variants.get(baseline_variant))
    return {
        variant_id: {
            "pass_rate_delta": round(float(_mapping(item).get("pass_rate") or 0) - float(baseline.get("pass_rate") or 0), 4),
            "average_quality_delta": round(
                float(_mapping(item).get("average_quality") or 0) - float(baseline.get("average_quality") or 0),
                4,
            ),
            "variant_quality_delta": round(
                float(_mapping(item).get("variant_quality") or 0) - float(baseline.get("variant_quality") or 0),
                4,
            ),
            "accept_rate_delta": round(float(_mapping(item).get("accept_rate") or 0) - float(baseline.get("accept_rate") or 0), 4),
        }
        for variant_id, item in variants.items()
    }


def _variant_ids(row: Mapping[str, Any]) -> dict[str, str]:
    for candidate in (
        _mapping(_mapping(row.get("metadata")).get("experiments")).get("variant_ids"),
        _mapping(row.get("experiment_variant_ids")),
        _mapping(_mapping(row.get("experiments")).get("variant_ids")),
        _mapping(_mapping(_mapping(row.get("response")).get("metadata")).get("experiments")).get("variant_ids"),
        _mapping(_mapping(row.get("actual")).get("experiment_variant_ids")),
    ):
        variants = _mapping(candidate)
        if variants:
            return {str(key): str(value) for key, value in variants.items() if key and value}
    return {}


def _is_accepted(row: Mapping[str, Any]) -> bool:
    if bool(row.get("accepted")):
        return True
    events = row.get("events")
    if isinstance(events, Sequence) and not isinstance(events, (str, bytes, bytearray)):
        for event in events:
            if isinstance(event, Mapping) and str(event.get("event_type") or event.get("type") or "") in ACCEPT_EVENT_TYPES:
                return True
    return False


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}
