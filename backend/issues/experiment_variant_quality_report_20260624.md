# Experiment Variant Quality Report - 2026-06-24

## Scope

ISS-025 asks for A/B experiment comparisons to connect `variant_id` with quality and behavior metrics. The runtime already assigns stable variants, persists assignments to trace/card payloads/user events, and produces experiment lift reports.

## Added

- `variant_quality` alias in each variant summary.
- `variant_quality_delta` in variant deltas.
- Markdown report column renamed to `Variant Quality`.
- Regression coverage to keep `variant_quality` present in JSON and Markdown reports.

## Existing Coverage

- Stable server-side assignment by user/device/conversation key.
- Client-provided variant overrides are preserved.
- Assignment metadata is merged into card feedback/user events.
- `experiment_lift_report.json` groups rows by experiment and variant.
- Behavior metric currently includes accept rate.

## Runtime Impact

No experiment changes affect product behavior in this slice. Variants remain observation-only unless a future reviewed rollout explicitly wires behavior changes.
