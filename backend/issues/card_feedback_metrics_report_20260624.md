# ISS-017 Card Feedback Metrics

## Scope

ISS-017 asks for recommendation-card feedback actions to become measurable signals:

- `feedback_rate`
- `negative_feedback_rate`

The product feedback routes already exist:

- `POST /v1/cards/{card_id}/accept`
- `POST /v1/cards/{card_id}/reject`
- `POST /v1/cards/{card_id}/change`
- `POST /v1/cards/{card_id}/ask-human`
- `POST /v1/cards/{card_id}/review`

This slice adds the missing ops metric surface. It does not change iOS, card behavior, recommendation strategy, or PipiLoop.

## Admin Surface

```text
GET /admin/api/cards/feedback-summary?since_hours=720
```

The endpoint uses the existing Admin auth and audit-log pattern.

## Metric Contract

`feedback_rate`

```text
feedback_card_count / recommendation_card_shown
```

`negative_feedback_rate`

```text
negative_feedback_card_count / recommendation_card_shown
```

Negative feedback event types:

- `recommendation_card_rejected`
- `recommendation_card_changed`
- `ask_human_requested`
- `recommendation_card_post_review_regretted`
- `recommendation_card_post_review_not_went`

Positive feedback event types:

- `recommendation_card_accepted`
- `final_recommendation_accepted`
- `recommendation_card_post_review_satisfied`

The summary also reports:

- feedback event counts by type
- per-core-feedback event coverage
- `intent_answer_feedback_link_rate`

## Example Output

```json
{
  "counts": {
    "recommendation_card_shown": 5,
    "feedback_event_count": 5,
    "feedback_card_count": 4,
    "positive_feedback_card_count": 1,
    "negative_feedback_card_count": 4,
    "neutral_feedback_card_count": 0,
    "intent_answer_linked_feedback_event_count": 2
  },
  "rates": {
    "feedback_rate": 0.8,
    "positive_feedback_rate": 0.2,
    "negative_feedback_rate": 0.8,
    "negative_feedback_share": 1.0,
    "intent_answer_feedback_link_rate": 0.4
  }
}
```

## Tests

Added no-DB coverage:

```text
backend/app/tests/test_card_feedback_metrics.py
```

The test verifies:

- accepted/rejected/changed/ask-human/post-review events are counted
- negative feedback rate is computed
- events can be linked back to cards with IntentAnswer provenance
- empty denominators return `null` rates

## Notes

This complements:

- `backend/issues/card_feedback_routes_report_20260623.md`
- `backend/issues/user_signal_summary_report_20260624.md`
- `backend/issues/final_recommendation_acceptance_report_20260624.md`
