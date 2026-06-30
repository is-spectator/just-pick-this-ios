# ISS-015 Personalization Metrics

## Scope

ISS-015 asks for measurable personalization feedback, especially:

- `preference_hit_rate`
- `personalized_acceptance_lift`

This change adds the metric surface only. It does not change routing, recommendation strategy, prompt policy, or mobile behavior.

## Runtime Surface

Admin endpoint:

```text
GET /admin/api/personalization/summary?since_hours=720
```

The endpoint uses the existing Admin auth and audit-log pattern. It returns a summary over recent recommendation cards and user behavior events.

## Metric Contract

`preference_hit_rate`

```text
personalized_card_count / recommendation_card_shown
```

A card is counted as personalized when its payload includes one of:

- `preference_rule_name`
- `preference_source`
- `area_food_preference`
- `personalization`
- matching fields under `metadata` or `provenance`

`personalized_acceptance_lift`

```text
personalized_acceptance_rate - baseline_acceptance_rate
```

Accepted cards are counted from behavior events:

- `recommendation_card_accepted`
- `final_recommendation_accepted`

## Output Shape

```json
{
  "counts": {
    "recommendation_card_shown": 4,
    "personalized_card_count": 2,
    "baseline_card_count": 2,
    "personalized_accepted_count": 2,
    "baseline_accepted_count": 1,
    "accepted_card_count": 3
  },
  "rates": {
    "preference_hit_rate": 0.5,
    "personalized_acceptance_rate": 1.0,
    "baseline_acceptance_rate": 0.5,
    "personalized_acceptance_lift": 0.5
  },
  "personalization_sources": {
    "query": 1,
    "user_memory": 1
  }
}
```

## Tests

Added no-DB unit coverage in:

```text
backend/app/tests/test_personalization_metrics.py
```

The test verifies:

- personalized cards are detected from query and memory metadata
- accepted personalized cards and baseline cards are counted separately
- acceptance lift is computed
- empty denominators return `null` rates instead of crashing

## Notes

This completes the ISS-015 measurement surface. Product personalization behavior remains covered by the existing product-path tests and report:

```text
backend/issues/personalization_product_path_report_20260624.md
```
