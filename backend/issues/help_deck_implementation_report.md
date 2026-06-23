# Help Deck Implementation Report 2026-06-15

## Scope

Implemented the first native “求一个 / 来一句” deck slice:

- Backend help-feed contract for one-card-at-a-time deck rendering.
- Backend one-liner validation, answer count update, reward payload, and pending reward ledger.
- Native iOS Answer screen as a swipeable card deck with bottom one-liner composer.

No recommendation-card behavior, PipiLoop architecture, real LLM path, payment, or cashout logic was changed.

## Backend Changes

- Added `RewardEvent` model and Alembic migration `0011_reward_events`.
- Extended help-card serialization with:
  - `context_text`
  - `answer_count`
  - stable `reward { label, value, status }`
- Updated `GET /v1/help-feed`:
  - returns only `published` / `collecting`
  - excludes owner’s cards
  - excludes cards already answered by the requester
  - excludes closed/final-ready through status filtering
  - sorts lower `answer_count` first, then newer published cards
  - supports `limit` and offset-style `cursor`
- Updated `POST /v1/help-cards/{id}/one-liner`:
  - trims input
  - rejects text shorter than 2 chars or longer than 240 Unicode chars
  - preserves owner self-answer guard
  - preserves duplicate answer guard
  - writes `HelpAnswer`
  - increments `HelpCard.answer_count`
  - writes pending `RewardEvent`
  - returns `reward`, `toast`, and `should_advance`
- Added optional `GET /v1/rewards/me`.

## iOS Changes

- Replaced the old answer-page scroll layout with a single-card deck.
- Added horizontal swipe to advance to the next help card.
- Added side-peek visual for the next card.
- Kept a persistent bottom one-liner input bar.
- Submit flow:
  - validates at least two characters locally
  - posts one-liner
  - shows reward toast
  - auto-advances to the next card
- Added loading and empty states.
- Extended `HelpRequest` and API decoding with reward label, answer count, and `context_text`.

## Manual QA Checklist

1. Open “来一句”.
2. Confirm only one large card is visible, with a subtle side peek.
3. Swipe left or right; the deck advances without opening a detail page.
4. Type a one-liner and send.
5. Confirm toast appears and the next card is shown.
6. Confirm no extra “求助 / skip / detail” controls are visible.
7. Confirm empty state appears when no cards remain.

## Verification

- `cd backend && uv run pytest app/tests/test_help_deck_api.py -q -rx`: passed.
- One-liner/finalize regression subset: passed.
- `cd backend && uv run pytest -q -rx`: passed.
- `cd backend && uv run alembic heads && uv run alembic current`: `0011_reward_events (head)`.
- `cd backend && uv run ruff check app tests`: passed.
- `xcodebuild -scheme JustPickThisIOS -configuration Debug -destination 'platform=iOS Simulator,name=iPhone 16 Pro,OS=18.3.1' build`: passed.

## Notes

- Production must run Alembic migration `0011_reward_events` before handling new one-liner reward writes.
- Reward events are an internal pending ledger only; no cashout or payment flow was added.
- Test/dev seed cards should remain explicit. Production auto-seeding is not enabled.
