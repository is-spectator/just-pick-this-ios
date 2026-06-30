# Card Ask-Human Feedback Report - 2026-06-24

## Scope

This slice closes the backend route gap in `ISS-017 Feedback UX`: card accept,
reject, change, and post-experience review already had dedicated APIs, but
"问真人" still required clients to hand-craft a generic `/v1/events` payload.

No iOS changes, agent routing changes, recommendation regeneration, or database
migration were made.

## Changes

- Added `POST /v1/cards/{card_id}/ask-human`.
- The route validates the recommendation card exists.
- The route sets the card status to `asked_human`.
- The route writes a bound `UserBehaviorEvent`:
  - `event_type=ask_human_requested`
  - `recommendation_card_id=<card_id>`
  - `conversation_id=<card.conversation_id>`
  - experiment metadata inherited from the card payload
- The response uses the existing `CardFeedbackResponse` shape.

Example response:

```json
{
  "card_id": "...",
  "accepted": false,
  "feedback": {
    "action": "ask_human",
    "status": "asked_human",
    "previous_status": "shown"
  },
  "event": {
    "event_type": "ask_human_requested"
  }
}
```

## IntentAnswer Memory

`ask_human_requested` is intentionally not a success or rejection signal for
`IntentAnswer`. Asking a person means the user wants more human evidence; it
does not prove the seed answer was wrong.

## Tests

Added/updated:

- `test_card_ask_human_route_writes_bound_feedback_event`
- `test_card_ask_human_does_not_penalize_intent_answer_memory`

Local targeted command:

```bash
uv run --extra dev pytest app/tests/test_user_behavior_events.py app/tests/test_p10_intent_answer_memory.py -q -rx
uv run --extra dev ruff check app tests
```

Note: DB integration tests are skipped locally when `DATABASE_URL` is not
reachable; GitHub backend CI runs with a real database and is the authoritative
DB-path verification.
