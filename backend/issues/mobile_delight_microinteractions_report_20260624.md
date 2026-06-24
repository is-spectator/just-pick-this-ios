# ISS-030 Mobile Delight Microinteractions

Date: 2026-06-24

## Scope

This change addresses the Mobile Delight issue from `pipi_effect_iteration_issues.xlsx`:

- improve recommendation card readability
- make core card actions easier to perceive
- make the help-card deck feel more swipeable
- keep the change constrained to SwiftUI presentation

No backend Agent logic, recommendation strategy, API contract, or database behavior changed.

## Changes

### Recommendation Card

- Added a subtle spring entrance for `ChatRecommendationCard`.
- Reduced oversized title typography and allowed longer titles to fit on one card.
- Increased decision reason line capacity so the card remains readable without scrolling.
- Added spring animation to the accept button state.
- Added selection haptic feedback when the accept action enters confirmation state.

### Help Deck

- Added drag-progress interpolation so the next help card rises as the user swipes.
- Added a slight scale response to the active card during drag.
- Added selection haptic feedback when a swipe is committed.
- Kept the existing one-liner toast and submission flow unchanged.

## Acceptance Mapping

- `session_depth`: deck cards now expose the next card during drag, making continued browsing more obvious.
- `one_liner_submit_rate`: the deck still keeps the composer as the primary action, with a clearer swipe affordance.
- `core actions`: recommendation cards keep the two visible actions, `求一个` and `就这个`, with stronger state feedback.
- `one screen readability`: recommendation title and decision text now tolerate longer venue names and route snippets.

## Validation

Run:

```bash
xcodebuild -project JustPickThisIOS.xcodeproj \
  -scheme JustPickThisIOS \
  -sdk iphonesimulator \
  -destination 'platform=iOS Simulator,name=iPhone 16 Pro' \
  build
```

