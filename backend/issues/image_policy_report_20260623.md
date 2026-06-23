# ISS-019 Image Policy Report

## Scope

This slice hardens the backend image policy without changing recommendation strategy, mobile UI, or enabling new image fetch behavior.

## Changes

- Recommendation card API image payload now exposes `displayable` and `verification_status`.
- Runtime card serialization returns image `displayable`, `verification_status`, `source_url`, and `source_domain`.
- Evaluator now treats an attached image as valid only when it is:
  - verified
  - displayable
  - non-AI
  - backed by `source_url`
  - backed by `source_domain`
- No-image recommendation cards remain valid when they have evidence.
- Quality scoring now treats images without source attribution as untrusted and records explicit source-missing issues.

## Contract

Recommendation cards may omit images. If an image is present, the response must include:

```json
{
  "source_url": "...",
  "source_domain": "...",
  "displayable": true,
  "verified": true,
  "verification_status": "verified",
  "is_ai_generated": false
}
```

## Verification

- Added evaluator tests for:
  - no-image card passes with evidence
  - non-displayable image fails
  - missing source URL/domain fails
  - verified/displayable/non-AI image with source passes
- Added card v2 response contract test for trusted image fields.
- Added quality scoring test for missing image source attribution.

