# Experimentation Slice

## Scope

This slice adds V0 experiment assignment plumbing for ISS-025 without changing
product behavior.

## What Changed

- Added deterministic experiment assignments in `app.services.experiments`.
- Product `/v1/chat/turn` now attaches `experiment_assignments` to:
  - request `client_context`
  - `AgentRun.input_json`
  - `AgentRun.output_json.metadata`
  - response `metadata.experiments`
  - recommendation-card and help-card payloads created during the turn
- Card feedback events inherit assignments from the card payload, so users do
  not need to echo variant metadata from the client.
- Generic behavior events also inherit assignments from related cards/help
  cards when available.

## Product Safety

- Assignments are observation-only.
- No routing, prompt, tool-call, card copy, or layout behavior changes.
- Client-provided assignments can override the default server hash, which makes
  future controlled experiments and ops replay possible.

## Default V0 Experiment

- `pipi_card_copy_v1`
  - variants: `control`, `concise_copy`
  - assignment source: stable server hash unless overridden by client context

## Tests

- `test_experiments.py`
- `test_chat_turn_and_card_feedback_preserve_experiment_assignment`

## Follow-ups

- Add experiment registry controls in ops.
- Add quality/behavior lift reporting by variant.
- Only after review, allow specific variants to alter card copy/prompt packs.
