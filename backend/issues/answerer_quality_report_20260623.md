# Answerer Quality Report 2026-06-23

## Scope

Implemented the first backend-only slice of ISS-023 Answerer Quality. This does
not change iOS, recommendation routing, finalizer ranking, or reward settlement.

## Changes

- Added conservative one-liner quality helpers in `app.services.help_service`.
- Rejected obvious low-value answers before they enter the reward queue:
  - generic answers such as `随便`, `不知道`, `好吃`
  - repeated-character spam
  - numeric-only answers
  - low-entropy filler
- Added duplicate detection per help card using a normalized punctuation-free
  key, including duplicates submitted by different users.
- Stored quality metadata and normalized key in `HelpAnswer.evidence_json` for
  accepted answers.
- Applied the same validation to:
  - public `/v1/help-cards/{id}/one-liner`
  - DB-backed product tool path
  - generic SQL tool path

## Behavior

- Low-quality one-liners return `422 one_liner_low_quality` and create no
  `HelpAnswer` or `RewardEvent`.
- Duplicate one-liners return `409 duplicate_answer` and do not increment
  `answer_count`.
- Valid one-liners still receive `reward_status=pending` and continue through
  the existing finalizer/reward flow.

## Verification

```bash
cd backend
uv run --extra dev pytest app/tests/test_one_liner_quality.py -q -rx
uv run --extra dev pytest app/tests/test_one_liner_quality.py app/tests/test_help_deck_api.py -q -rx
uv run --extra dev ruff check app tests
```

`test_help_deck_api.py` remains a DB integration suite and is skipped when
`DATABASE_URL` is not reachable; `test_one_liner_quality.py` runs without DB.

## Remaining Work

- Add semantic duplicate detection beyond exact normalized text.
- Add answerer reputation and moderation queues.
- Feed answer-quality labels into finalizer evidence selection and ops review.
