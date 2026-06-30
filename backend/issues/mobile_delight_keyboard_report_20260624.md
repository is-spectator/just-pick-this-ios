# ISS-030 Mobile Delight Keyboard Report

## Scope

This slice makes the chat composer easier to use on device without changing backend behavior, recommendation strategy, or app navigation.

## Changes

- The composer now clears focus before sending a message.
- The keyboard toolbar now exposes a clear `收起` action for dismissing Chinese/number keyboards on real devices.
- The composer automatically releases focus when `isSending` becomes true, so the keyboard does not stay pinned over recommendation/help cards while the request is in flight.

## Why This Helps

ISS-030 asks for smoother interaction and core actions that do not require thinking. The most visible real-device friction reported by testing was the keyboard staying open after a recommendation flow. This change gives users an explicit escape hatch and a deterministic send-time dismissal.

## Verification

- Build verification: `xcodebuild -project JustPickThisIOS.xcodeproj -scheme JustPickThisIOS -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build`.
