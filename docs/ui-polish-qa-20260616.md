# UI Polish QA 2026-06-16

## Scope

This QA pass covers only the native iOS SwiftUI surface:

- `NativeApp/Screens.swift`
- `NativeApp/Components.swift`

No backend, API contract, Agent runtime, database, or LLM path was changed in this UI polish pass.

## Recommendation Card Checklist

- The chat recommendation card shows one primary title and one decision reason.
- Bullets, followups, warning blocks, and "猜你想问" style prompts are not rendered in the chat card.
- The older result card path now follows the same one-choice layout.
- If a verified image URL exists, it is shown as a large top hero image.
- If no image exists, the card does not render an empty placeholder.
- The actions are limited to two capsule buttons: `求一个` and `就这个`.
- Button hit targets are at least 44 pt.

## Help Deck Checklist

- `AnswerScreen` has a page title `来一句` and supporting copy `帮 TA 少纠结一次。`.
- `HelpDeckCard` uses a left-aligned hierarchy instead of centered low-fidelity layout.
- The next card remains partially visible to suggest horizontal swiping.
- The card does not show list rows, detail forms, `帮她选`, or `跳过`.
- The answer composer placeholder adapts to the current help card when possible.
- Toast copy uses the current reward label, such as `+10` or `+8`.

## Navigation And Copy Checklist

- The homepage top bar shows `皮皮` as the title.
- Primary top actions are limited to three: `历史`, `新对话`, `来一句`.
- Account access moved out of the main top bar and into the history sheet.
- User-facing copy no longer says `历史 session`.
- Loading copy says `正在取求一个`.
- Empty answer queue copy says `暂时没有求一个` and `晚点再来，或者自己发一个。`.

## Composer And Toast Checklist

- `BottomComposer` keeps the capsule style.
- The send button visual circle stays compact, while the tappable area is at least 44 pt.
- The input height is consistent across chat, ask, result, and answer screens.
- Toast remains short and does not cover the core deck title.

## SwiftUI Previews

Added or kept previews for:

- `InputScreen`
- `ResultScreen`
- `AskScreen`
- `AnswerScreen`
- `ChatRecommendationCard` with image
- `ChatRecommendationCard` without image
- `ChatHelpCard` draft
- `HelpDeckCard`
- `BottomComposer`

## Known Limits

- Image loading failure currently leaves the image area blank only when a URL exists but fails to load. No-image cards still correctly omit the image area entirely.
- The old `TopPick` model still contains legacy fields for API compatibility, but the polished card UI does not render them.
