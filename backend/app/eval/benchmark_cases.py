"""Benchmark case loading and filtering helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.eval.reporting import load_benchmark_cases


def load_product_benchmark_cases(
    path: str | Path,
    *,
    limit: int | None = None,
    group: str | None = None,
    case_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Load benchmark cases with deterministic product-run filtering."""

    wanted_ids = {str(case_id) for case_id in case_ids or []}
    cases: list[dict[str, Any]] = []
    for case in load_benchmark_cases(path):
        if not isinstance(case, Mapping):
            continue
        case_group = str(case.get("category") or case.get("group") or "unknown")
        case_id = str(case.get("id") or case.get("case_id") or "")
        if group and case_group != group:
            continue
        if wanted_ids and case_id not in wanted_ids:
            continue
        cases.append(dict(case))
        if limit is not None and len(cases) >= limit:
            break
    return cases
