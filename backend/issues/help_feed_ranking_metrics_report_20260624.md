# Help Feed Ranking Metrics Report - 2026-06-24

## Scope

ISS-022 focuses on making the help feed surface cards that are easiest and most worthwhile for answerers. The current ranking path already scores by reward value, answer scarcity, answer count, and answerer preference match. This change completes the measurement layer by adding skip-rate visibility.

## Existing Ranking Signals

`help_feed_rank_payload` exposes:

- `reward_value`
- `answer_count`
- `min_answers_required`
- `remaining_answers`
- `preference_match`
- `score`

`help_feed_sort_key` sorts by:

1. ranking score;
2. reward value;
3. lower answer count;
4. published/created recency.

## Added Metrics

`help_feed_conversion_summary` now includes `help_card_skipped` events and reports:

- `one_liner_submit_rate`
- `skip_rate`
- `total_submitted_after_impression`
- `total_skipped_after_impression`
- segment-level `skipped_pairs` and `skip_rate`

## Acceptance Link

The target `one_liner_submit_rate +20%` can now be evaluated together with `skip_rate`, so ranking changes can be judged by both increased answer submissions and lower feed skips.

## Runtime Impact

No iOS or product ranking behavior changed in this slice. The update is read-only measurement plus regression coverage.
