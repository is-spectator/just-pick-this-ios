# ISS-012 Prompt Ops Trace Report

## Scope

This slice hardens Prompt Ops observability without changing routing, recommendation strategy, iOS, or prompt content.

## Changes

- Product `/v1/chat/turn` responses now expose `metadata.prompt_versions` for the active prompt pack.
- The payload is a safe summary only: `version_id`, `version`, `checksum`, `status`, `environment`, and `rollout_percent`.
- Prompt content is intentionally not returned in product responses.
- Existing AgentRun input trace storage remains unchanged, so Ops Trace Replay and API responses now share the same prompt-version attribution surface.

## Verification

- Added product-path trace regression coverage that asserts:
  - `metadata.prompt_versions.reasoner.system.version >= 1`.
  - no prompt `content` field is exposed in the product response.

## Notes

Existing Prompt Ops capabilities already include draft, dry-run, publish, rollback, active prompt pack registry, admin audit, and trace replay endpoints.
