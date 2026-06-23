# Email Auth Audit 2026-06-15

## Current State

1. `User` currently stores `id`, `device_uid`, `display_name`, platform/version/locale/timezone, `last_seen_at`, and `profile_json`. This iteration adds email auth fields.
2. `device_uid` is generated on iOS in `DeviceIdentity.uid`, currently persisted through `UserDefaults` under `just_pick_this_device_uid`, and sent as `device_id` to backend APIs.
3. `/v1/bootstrap` is still used. It calls `ensure_user(... device_uid ...)`, creates a user for the device, and creates a new conversation.
4. `/v1/chat/turn` resolves user through `_resolve_conversation_and_user`, which currently uses `device_id/device_uid` and optionally `user_id`.
5. There is no product user token/session concept. Admin/debug tokens are separate Bearer token guards and do not represent end users.
6. iOS persists device UID locally and sends it on every backend request. There is no Keychain auth token storage yet.
7. Admin/debug Bearer tokens are independent routes and should not conflict with user Authorization Bearer as long as product auth is resolved only in `/v1` user APIs.
8. No email/SMTP configuration currently exists before this iteration.

## Required Changes

- Add `email`, verification/login/status fields to `User`.
- Add `EmailLoginCode`, `AuthSession`, `AuthAuditLog`, and `UserDevice`.
- Add SMTP email provider and console provider for development/test.
- Add `/v1/auth/request-code`, `/v1/auth/verify-code`, `/v1/auth/refresh`, `/v1/auth/logout`, and `/v1/auth/me`.
- Add access-token verification and refresh-token rotation.
- Make `/v1/chat/turn` prefer authenticated user when Authorization Bearer is present, while still allowing anonymous `device_uid`.
- Add iOS email-code login UI and Keychain-backed token storage.

## Risk

- Device/conversation ownership checks must allow login users to continue old device conversations after merge.
- Production must reject missing `JWT_SECRET` and console email provider.
- SMTP passwords must never be logged or checked into docs/tests.
- Auth changes must not change PipiLoop or recommendation behavior.

## Files to Modify

- `backend/app/config.py`
- `backend/app/models/runtime.py`
- `backend/app/models/__init__.py`
- `backend/app/api/__init__.py`
- `backend/app/api/routes_auth.py`
- `backend/app/services/auth_service.py`
- `backend/app/services/email_service.py`
- `backend/app/services/email_templates.py`
- `backend/app/services/user_merge_service.py`
- `backend/app/services/chat.py`
- `backend/app/schemas/auth.py`
- `NativeApp/MockData.swift`
- `NativeApp/RootView.swift`
- `NativeApp/Screens.swift`

## Tests to Add

- `test_email_service.py`
- `test_email_auth_api.py`
- `test_user_merge_service.py`
- `test_auth_security.py`
