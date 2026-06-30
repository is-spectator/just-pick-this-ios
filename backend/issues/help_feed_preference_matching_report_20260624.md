# Help Feed Preference Matching Report - 2026-06-24

## Scope

This slice closes the answerer-preference tail from `ISS-022 Help Feed Ranking`.
It does not change iOS, reward settlement, PipiLoop behavior, finalizer logic, or
the recommendation strategy.

## Changes

- `/v1/help-feed` now reads the requesting user's
  `profile_json.preference_memory_v1.summary`.
- Feed ranking includes a deterministic `preference_match` payload:
  - `score`
  - matched preference buckets
  - candidate terms found on the help card
- Preference matching is applied as a same-tier ranking booster on top of the
  existing feed score:
  - reward value
  - remaining answers needed
  - answer count
  - answerer preference match
  - publish/create recency
- Feed item metadata exposes the match evidence under:

```json
{
  "metadata": {
    "feed_ranking": {
      "preference_match": {
        "score": 55,
        "matched": {
          "top_cuisines": ["韩餐"],
          "areas": ["五道口"]
        }
      }
    }
  }
}
```

## Preference Buckets

The V1 matcher uses existing preference-memory summaries only:

- `top_cuisines`
- `top_food_items`
- `taste_preferences`
- `spice_preferences`
- `budget_preferences`
- `companions`
- `areas`
- `accepted_items`

The matcher is intentionally conservative. It does not override major reward
differences; it improves ordering among otherwise similar cards, which is the
safer product behavior until real answerer conversion data is available.

## Issue Coverage

- Advances `ISS-022 Help Feed Ranking`: answerers now see cards closer to their
  known interests first.
- Builds on `ISS-015 User Preference Memory`: stored preference summaries now
  affect a product surface.
- Complements `help_feed_signal_events_report_20260624.md`: impressions/skips
  can now be analyzed alongside match score.

## Tests

Added/updated:

- `test_help_feed_rank_payload_exposes_answerer_preference_match`
- `test_help_feed_sort_uses_preferences_as_same_tier_tiebreaker`
- `test_help_feed_ranks_answerer_preference_within_same_tier`

Local targeted command:

```bash
uv run --extra dev pytest app/tests/test_help_feed_ranking.py app/tests/test_help_deck_api.py -q -rx
uv run --extra dev ruff check app tests
```

Note: DB integration tests are skipped locally when `DATABASE_URL` is not
reachable; GitHub backend CI runs with a real database and is the authoritative
DB-path verification.
