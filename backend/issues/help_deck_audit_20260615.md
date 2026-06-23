# Help Deck Audit 2026-06-15

## Current API

1. `GET /v1/help-feed` exists and is implemented by `app.services.help_feed.list_help_feed`.
2. `POST /v1/help-cards/{help_card_id}/one-liner` exists and is implemented by `create_one_liner`.
3. `HelpCard` already has `owner_user_id`, `title`, `prompt`, `context_text`, `status`, `answer_count`, `min_answers_required`, `payload_json`, `published_at`, and `final_ready_at`.
4. `HelpAnswer` already has `answer_user_id`, `raw_text`, `normalized_text`, `status`, `reward_status`, and `evidence_json`.
5. Reward state exists on answers as `reward_status`, but there was no ledger table before this iteration.
6. `RewardEvent` has now been added as the pending reward ledger for one-liner submissions.
7. Feed filtering already excluded the owner and already-answered cards, but it previously applied SQL `limit` before the answered-card filter and sorted newest-first. It now filters in SQL and sorts by lower `answer_count` first.
8. Owner self-answer protection already existed and remains enforced with `403`.
9. `answer_count` already incremented on one-liner submit.
10. Finalization already triggers when `answer_count >= min_answers_required` through `run_finalize_graph_for_help_card`.

## Gaps Found

- Feed payload was a generic help-card serializer, not deck-optimized. It lacked top-level `context_text`, `answer_count`, stable reward status, and cursor behavior.
- One-liner accepted one-character or whitespace-heavy text because schema only required `min_length=1`.
- One-liner response lacked `reward` and `should_advance`, forcing the iOS client to hardcode toast behavior.
- No reward ledger existed, so pending rewards were not auditable.
- Feed returned newest cards first instead of prioritizing cards with fewer answers.

## Fixes In This Iteration

- Added `RewardEvent` model and migration `0011_reward_events`.
- Added deck fields to `HelpCardSummary`.
- Added `reward` and `should_advance` to `HelpCardOneLinerResponse`.
- Tightened feed filtering/sorting and cursor support.
- Added one-liner text validation: trimmed, at least 2 chars, at most 240 Unicode characters.
- Added top-level reward return and pending reward ledger write.

## Remaining Notes

- Production auto-seeding remains disabled. Test/dev seed data should be created explicitly by tests or local seed scripts.
- Reward events are only a ledger for pending app rewards; no payment or cashout behavior is included.
