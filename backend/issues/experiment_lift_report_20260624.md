# ISS-025 Experiment Lift Report Slice

## Scope

This slice extends the existing observation-only experiment assignment plumbing with benchmark/reporting lift summaries. It does not change routing, prompts, tools, cards, or iOS.

## What Changed

- Added `app.eval.experiment_lift`.
- `write_quality_reports(...)` now emits:
  - `experiment_lift_report.md`
  - `experiment_lift_report.json`
- Report groups benchmark rows by `metadata.experiments.variant_ids`.
- Each variant summary includes:
  - case count
  - pass rate
  - average quality
  - accepted rate
  - deltas versus `control`

## Product Safety

- Experiment assignments remain observation-only.
- No variant changes product behavior.
- Lift reporting works from result rows after benchmark execution.

## Follow-ups

1. Add behavior-event backed lift reports from production traffic.
2. Add ops guardrails before any variant can alter prompt/card copy.
3. Add minimum sample-size warnings before reading deltas.

