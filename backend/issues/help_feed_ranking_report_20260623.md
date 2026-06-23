# Help Feed Ranking Report 2026-06-23

## Scope

Implemented the first backend-only slice of ISS-022 Help Feed Ranking. This does
not change iOS, reward settlement, finalizer behavior, or answerer preference
memory.

## Changes

- `/v1/help-feed` now sorts candidate cards with a deterministic feed rank.
- Ranking uses existing data only:
  - reward value, descending
  - remaining answers needed before finalization
  - lower answer count
  - publish/create recency as tie-breakers
- Help feed items expose `metadata.feed_ranking` so ops/eval can inspect why a
  card was shown earlier.
- Owner filtering and already-answered filtering remain in place.

## Behavior

- Higher reward cards are surfaced earlier.
- Cards that still need more answers are prioritized over already-filled cards.
- The response contract remains compatible because ranking details live under
  existing `metadata`.

## Verification

```bash
cd backend
uv run --extra dev pytest app/tests/test_help_feed_ranking.py app/tests/test_help_deck_api.py -q -rx
uv run --extra dev ruff check app tests
```

`test_help_deck_api.py` is a DB integration suite and is skipped when
`DATABASE_URL` is not reachable; `test_help_feed_ranking.py` runs without DB.

## Remaining Work

- Add answerer preference matching.
- Add skip/impression events to measure feed ranking quality.
- Add abuse/moderation weighting once unsafe content flags exist.
