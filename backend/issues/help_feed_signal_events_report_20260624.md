# Help Feed Signal Events Report - 2026-06-24

## Scope

This slice closes the measurement gap in the help-feed loop without changing iOS or agent routing logic.

Implemented:

- Records `help_feed_impression` events when `/v1/help-feed` returns visible help cards.
- Records `help_card_skipped` events when a user skips a help card.
- Excludes help cards previously skipped by the same user from future feed results.
- Marks both event types as core behavior events so downstream preference, trace, and analytics jobs can distinguish them from ad hoc events.

## Runtime Contract

### GET `/v1/help-feed`

When `device_uid`, `device_id`, or `user_id` resolves to a user, each returned help card writes one `UserBehaviorEvent`:

- `event_type=help_feed_impression`
- `source=help_feed`
- `help_card_id=<visible card>`
- `payload_json.rank_index`
- `payload_json.page_index`
- `payload_json.limit`
- `payload_json.cursor`
- `payload_json.shown_help_card_ids`
- `payload_json.feed_ranking`

Anonymous calls without a resolvable user still return feed items, but do not write impression events.

### POST `/v1/help-cards/{help_card_id}/skip`

Request:

```json
{
  "device_uid": "reader-device",
  "reason": "not_relevant",
  "metadata": {}
}
```

Response:

```json
{
  "ok": true,
  "help_card_id": "...",
  "event": {
    "event_type": "help_card_skipped",
    "metadata": {
      "reason": "not_relevant"
    }
  }
}
```

Rules:

- Requires `device_uid`, `device_id`, or `user_id`.
- Owner cannot skip their own help card.
- Skip is a user-level signal; it does not mutate the help card status.
- Future `/v1/help-feed` results for the same user exclude skipped cards.

## Issue Coverage

- Advances `ISS-022 Help Feed Ranking`: ranking quality can now be measured through impressions and skips.
- Advances `ISS-008 User Signals`: skip behavior becomes a first-class persisted product signal.
- Complements `ISS-024 Abuse Safety`: unsafe cards are filtered; safe but irrelevant cards can now be skipped per user.

## Tests

Added coverage in `app/tests/test_help_deck_api.py`:

- `test_help_feed_records_impressions_for_visible_cards`
- `test_skip_help_card_records_signal_and_hides_for_same_user`

Local targeted command:

```bash
uv run --extra dev pytest app/tests/test_help_deck_api.py app/tests/test_help_feed_ranking.py -q -rx
uv run --extra dev ruff check app tests
```

Note: DB integration tests are skipped locally when `DATABASE_URL` is not reachable; GitHub backend CI runs with a real database and is the authoritative DB-path verification.
