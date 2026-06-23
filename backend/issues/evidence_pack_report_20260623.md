# Retrieval Evidence Pack Report

Date: 2026-06-23

## Issue

Addresses the ISS-014 slice from `pipi_effect_iteration_issues.xlsx`: retrieval evidence needed a stable, replayable pack instead of ad hoc `retrieval_hits` and `strongest_evidence` arrays.

## What Changed

- Added `app.retrieval.evidence_pack`.
- Standardized retrieval hits into `evidence_pack_v1` with:
  - layer summaries
  - strongest evidence
  - local memory / human evidence / web evidence / verified image / place / route flags
  - missing layer attribution
- `ContextBuilder` now attaches `evidence_pack` and a compact summary under `retrieval_summary.evidence_pack`.
- DB-backed `search_knowledge` now returns `evidence_pack` and `evidence_pack_summary` in its `ToolResult`.
- `PipiLoop` feeds `evidence_pack` forward after `search_knowledge`, so the next reasoner iteration and loop trace can inspect it.

## Non-goals

- No Tavily calls were added.
- No AMap calls were added.
- No card selection strategy changed.
- No image requirement changed.
- No database migration was needed.

## Tests

- `app/tests/test_evidence_pack.py`
- `app/tests/test_context_builder.py`

## Expected Runtime Impact

Product behavior should remain unchanged. The new pack only improves trace readability, eval attribution, and future evidence policy work.
