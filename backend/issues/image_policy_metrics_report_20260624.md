# ISS-019 Image Policy Metrics

## Scope

ISS-019 requires reference-image safety and measurable image quality:

- `image_attach_rate`
- `bad_image_rate`

The backend already enforces image safety at card serialization/evaluator layers:

- images are optional
- attached images must be verified
- attached images must be displayable
- attached images must be non-AI
- attached images must include `source_url` and `source_domain`

This slice adds the missing read-only ops metric surface. It does not change Tavily fetching, image selection, recommendation strategy, or iOS.

## Admin Surface

```text
GET /admin/api/images/policy-summary?since_hours=720
```

The endpoint uses the existing Admin auth and audit-log pattern.

## Metric Contract

`image_attach_rate`

```text
image_attached_card_count / recommendation_card_count
```

`bad_image_rate`

```text
bad_image_card_count / image_attached_card_count
```

Bad image means any attached image missing one of:

- verified / `verification_status=verified`
- `displayable=true`
- `is_ai_generated=false`
- `source_url`
- `source_domain`

The summary also reports `no_image_with_evidence_count`, because no-image recommendation cards are valid when evidence exists.

## Example Output

```json
{
  "counts": {
    "recommendation_card_count": 3,
    "image_attached_card_count": 2,
    "trusted_image_card_count": 1,
    "bad_image_card_count": 1,
    "missing_image_card_count": 1,
    "no_image_with_evidence_count": 1
  },
  "rates": {
    "image_attach_rate": 0.6667,
    "trusted_image_rate": 0.5,
    "bad_image_rate": 0.5,
    "no_image_with_evidence_rate": 1.0
  }
}
```

## Tests

Added no-DB coverage:

```text
backend/app/tests/test_image_policy_metrics.py
```

The tests verify:

- trusted image cards are counted separately from bad image cards
- missing `source_url/source_domain` marks an image bad
- no-image cards with evidence remain valid for the policy summary
- empty denominators return `null` rates

## Related Reports

- `backend/issues/image_policy_report_20260623.md`
- `backend/issues/evidence_quality_summary_report_20260624.md`
